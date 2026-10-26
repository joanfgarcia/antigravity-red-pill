"""Tests de inyección version-aware (V1 vs V2) del adapter opencode."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
INJECT_PATH = os.path.join(REPO_ROOT, "scripts", "inject", "opencode", "inject.py")
VERSION_PATH = os.path.join(REPO_ROOT, "scripts", "opencode_version.py")


def _load(name: str, path: str) -> object:
	spec = importlib.util.spec_from_file_location(name, path)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[name] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def inject_mod():
	return _load("opencode_inject_version_under_test", INJECT_PATH)


def _args() -> argparse.Namespace:
	return argparse.Namespace(
		redpill_dir=REPO_ROOT,
		uv_path="/usr/bin/uv",
		no_backup=True,
		update=False,
		workspace=None,
	)


def _run(inject_mod, monkeypatch, tmp_path, major: int, initial: dict | None = None) -> dict:
	config_dir = tmp_path / "oc"
	config_dir.mkdir()
	config_path = config_dir / "opencode.jsonc"
	if initial is not None:
		config_path.write_text(json.dumps(initial))

	ov = _load("opencode_version_for_inject", VERSION_PATH)
	info = ov.OpenCodeInfo(True, (major, 0, 0), f"{major}.0.0", major, "env")
	monkeypatch.setattr(inject_mod, "detect_info", lambda config_path=None: info)
	monkeypatch.setattr(inject_mod, "_detect_config_dir", lambda: str(config_dir))
	monkeypatch.setattr(inject_mod, "agent_core_vars", lambda: {"AGENT_CORE_DIR": "/tmp/desk"})

	inject_mod.inject(_args())
	return json.loads(config_path.read_text())


def test_v2_seed_migrates_v1_config(inject_mod, monkeypatch, tmp_path) -> None:
	initial = {
		"model": "x/y",
		"plugin": ["./plugins/redpill-scribe.js"],
		"mcp": {"RedPill-Kernel": {"type": "local", "command": ["py"], "enabled": True}},
		"permission": {"external_directory": {"*": "ask"}},
		"provider": {"p": {"npm": "@ai-sdk/openai-compatible", "options": {"baseURL": "https://api"}}},
		"skills": {"paths": ["~/.config/opencode/skills"]},
	}
	out = _run(inject_mod, monkeypatch, tmp_path, 2, initial)

	assert "plugin" not in out and "permission" not in out and "provider" not in out
	assert "servers" in out["mcp"] and "RedPill-Kernel" in out["mcp"]["servers"]
	assert isinstance(out["skills"], list)
	assert isinstance(out["permissions"], list)
	# catch-all first so specific allows win (last-match-wins)
	ext = [r for r in out["permissions"] if r.get("action") == "external_directory"]
	assert ext and ext[0]["resource"] == "*"
	assert "providers" in out

	pkg_path = tmp_path / "oc" / "package.json"
	if pkg_path.exists():  # V2 does not create the file; if present, no V1 pin
		assert "@opencode-ai/plugin" not in json.loads(pkg_path.read_text()).get("dependencies", {})

	agent = tmp_path / "oc" / "agents" / "forge-qa.md"
	assert agent.exists(), "agents must be seeded by the real inject_cli path"
	assert "permissions:" in agent.read_text() and "effect: deny" in agent.read_text()


def test_v1_seed_preserved(inject_mod, monkeypatch, tmp_path) -> None:
	out = _run(inject_mod, monkeypatch, tmp_path, 1, {"model": "x/y"})

	assert "plugin" in out
	assert "RedPill-Kernel" in out["mcp"] and "servers" not in out["mcp"]
	assert "permission" in out
	assert isinstance(out.get("skills"), dict) and "paths" in out["skills"]

	pkg = json.loads((tmp_path / "oc" / "package.json").read_text())
	assert "@opencode-ai/plugin" in pkg["dependencies"]


def test_seed_agents_are_v2_native() -> None:
	import glob

	files = glob.glob(os.path.join(REPO_ROOT, "seeds", "opencode", "agents", "*.md"))
	assert files
	for path in files:
		text = open(path, encoding="utf-8").read()
		front = text.split("---", 2)[1] if text.startswith("---") else ""
		assert "\npermission:" not in front, f"{path}: V1 'permission:' key must be gone"
		# Native V2: `version:` is not an agent field (V2 warns "unsupported").
		assert "\nversion:" not in front, f"{path}: unsupported 'version:' field in V2 agent"
		# V2: hidden agents are excluded from the subagent catalog, so FORGE
		# could not spawn them. Forge agents must stay visible.
		assert "\nhidden: true" not in front, f"{path}: forge agents must not be hidden in V2"
	qa = open(os.path.join(REPO_ROOT, "seeds", "opencode", "agents", "forge-qa.md"), encoding="utf-8").read()
	assert "permissions:" in qa and "effect: deny" in qa


def test_v2_second_run_converges(inject_mod, monkeypatch, tmp_path) -> None:
	first = _run(inject_mod, monkeypatch, tmp_path, 2, None)
	# Idempotency: re-run on the already-V2 file must not reintroduce V1 keys.
	config_dir = tmp_path / "oc"
	config_path = config_dir / "opencode.jsonc"
	config_path.write_text(json.dumps(first))
	inject_mod.inject(_args())
	second = json.loads(config_path.read_text())
	assert second == first
