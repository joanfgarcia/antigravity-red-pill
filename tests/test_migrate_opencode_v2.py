"""Tests de la migración de opencode.jsonc V1 -> V2 (scripts/migrate_opencode_v2.py).

Cubren los mapeos que rompían el arranque en V2: `mcp.servers`, orden
last-match-wins de `permissions`, `provider(s)`/`package`, el shape de modelo,
tuplas de plugins, JSONC con trailing commas e idempotencia.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MIGRATOR_PATH = os.path.join(REPO_ROOT, "scripts", "migrate_opencode_v2.py")


def _load_migrator() -> object:
	spec = importlib.util.spec_from_file_location("opencode_v2_migrator_under_test", MIGRATOR_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["opencode_v2_migrator_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def mig():
	return _load_migrator()


def _rules_by_action(perms: list, action: str) -> list:
	return [r for r in perms if r["action"] == action]


def test_mcp_moves_under_servers(mig) -> None:
	cfg = {"mcp": {"s1": {"type": "local", "command": ["x"], "enabled": False, "timeout": 1000}}}
	out, _, _ = mig.migrate(cfg, "/tmp")
	s1 = out["mcp"]["servers"]["s1"]
	assert s1["disabled"] is True
	assert "enabled" not in s1
	assert s1["timeout"] == {"catalog": 1000, "execution": 1000}
	assert "s1" not in out["mcp"]


def test_permissions_catch_all_first_and_last_match_wins(mig) -> None:
	cfg = {"permission": {"external_directory": {"/secret/**": "deny", "*": "allow"}, "task": {"forge-*": "allow"}}}
	out, _, _ = mig.migrate(cfg, "/tmp")
	ext = _rules_by_action(out["permissions"], "external_directory")
	# catch-all first, specific after -> last match (deny) wins for /secret/**
	assert ext[0]["resource"] == "*"
	assert ext[-1]["resource"] == "/secret/**"
	assert any(r["action"] == "subagent" and r["resource"] == "forge-*" for r in out["permissions"])


def test_permission_aliases_coalesce(mig) -> None:
	cfg = {"permission": {"write": "deny", "edit": "ask", "bash": {"git push *": "deny"}}}
	out, _, _ = mig.migrate(cfg, "/tmp")
	edit = _rules_by_action(out["permissions"], "edit")
	assert len(edit) == 1 and edit[0]["effect"] == "deny"
	assert _rules_by_action(out["permissions"], "shell")


def test_provider_and_model_shape(mig) -> None:
	cfg = {
		"provider": {
			"acme": {
				"api": "https://llm.example/v1",
				"npm": "@ai-sdk/openai-compatible",
				"models": {
					"m1": {
						"id": "upstream",
						"release_date": "2025-01",
						"options": {"temperature": 0.2},
						"modalities": {"input": ["text"], "output": ["text"]},
						"tool_call": True,
						"reasoning": True,
						"variants": {"fast": {"reasoningEffort": "low"}},
					}
				},
			}
		}
	}
	out, _, _ = mig.migrate(cfg, "/tmp")
	p = out["providers"]["acme"]
	assert p["package"] == "@opencode/ai/providers/openai-compatible"
	assert p["settings"]["baseURL"] == "https://llm.example/v1"
	m = p["models"]["m1"]
	assert m["modelID"] == "upstream"
	assert m["releaseDate"] == "2025-01"
	assert m["settings"] == {"temperature": 0.2}
	assert m["capabilities"]["tools"] is True
	assert m["capabilities"]["input"] == ["text"]
	assert m["capabilities"]["reasoning"] == {"supported": True}
	assert m["variants"] == [{"id": "fast", "settings": {"reasoningEffort": "low"}}]


def test_plugin_tuple_converted(mig) -> None:
	cfg = {"plugin": [["./plugins/p.js", {"x": 1}], "pkg"]}
	out, _, _ = mig.migrate(cfg, "/tmp/project")
	assert {"package": "./plugins/p.js", "options": {"x": 1}} in out["plugins"]
	assert "pkg" in out["plugins"]
	assert "plugin" not in out


def test_project_plugins_file_not_silently_dropped(mig, tmp_path) -> None:
	cfgdir = tmp_path / "project"
	(cfgdir / "plugins").mkdir(parents=True)
	(cfgdir / "plugins" / "p.js").write_text("// x\n")
	cfg = {"plugin": ["./plugins/p.js"]}
	out, _, warnings = mig.migrate(cfg, str(cfgdir))
	assert "p.js" in json.dumps(out)
	assert any("single file" in w for w in warnings)


def test_jsonc_trailing_comma_and_comments(mig, tmp_path) -> None:
	p = tmp_path / "opencode.jsonc"
	p.write_text('{\n  // c\n  "plugin": ["pkg",],\n  "theme": "dark",\n}\n')
	cfg = mig.load_jsonc(str(p))
	assert cfg["plugin"] == ["pkg"] and cfg["theme"] == "dark"


def test_idempotent_needs_migration(mig) -> None:
	cfg = {
		"plugin": ["pkg"],
		"mcp": {"s": {"type": "local", "command": ["x"]}},
		"permission": {"external_directory": {"*": "ask"}},
		"provider": {"p": {"npm": "@ai-sdk/openai-compatible"}},
		"default": {"provider": "p", "model": "m"},
	}
	assert mig._needs_migration(cfg) is True
	out, _, _ = mig.migrate(cfg, "/tmp")
	assert mig._needs_migration(out) is False
