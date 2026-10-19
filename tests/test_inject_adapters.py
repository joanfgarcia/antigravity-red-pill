"""Regresión: los adaptadores IDE resuelven bien la ruta a los scripts legacy.

El dispatcher `inject_cli.py` delega en adaptadores `scripts/inject/<ide>/inject.py`
que invocan `scripts/inject_{anchor,mcp,settings}.py`. Un `SCRIPTS_ROOT` con un
`..` de menos hacía que antigravity y claude-code **no inyectaran nada** en
silencio (el reseed no aplicaba hooks ni MCP)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ("antigravity", "claude-code", "opencode", "pi")
LEGACY_SCRIPTS = ("inject_anchor.py", "inject_mcp.py")


def _load(ide: str):
	path = REPO_ROOT / "scripts" / "inject" / ide / "inject.py"
	spec = importlib.util.spec_from_file_location(f"inj_{ide}", str(path))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


@pytest.mark.parametrize("ide", ADAPTERS)
def test_adapter_scripts_root_has_legacy_scripts(ide):
	"""Todo adaptador que use `SCRIPTS_ROOT` debe apuntar a `scripts/` (no a `scripts/inject/`)."""
	mod = _load(ide)
	root = getattr(mod, "SCRIPTS_ROOT", None)
	if root is None:
		pytest.skip(f"{ide} no usa SCRIPTS_ROOT (resuelve por sys.path)")
	root = Path(root).resolve()
	assert root == (REPO_ROOT / "scripts").resolve(), f"{ide}: SCRIPTS_ROOT={root}"
	for script in LEGACY_SCRIPTS:
		assert (root / script).exists(), f"{ide}: falta {script} en {root}"


@pytest.mark.parametrize("ide", ("antigravity", "claude-code"))
def test_adapter_redpill_dir_fallback_is_repo_root(ide):
	"""El fallback de `redpill_dir` (sin --redpill-dir) debe ser la raíz del repo."""
	mod = _load(ide)
	import argparse

	args = argparse.Namespace(redpill_dir=None, uv_path=None)
	# Reproduce la resolución del fallback sin ejecutar subprocess: parchea run.
	import types

	calls = {}

	def _fake_run(cmd, **kw):
		calls["cmd"] = cmd
		return types.SimpleNamespace(returncode=1, stdout="", stderr="")

	import unittest.mock as mock

	with mock.patch("subprocess.run", _fake_run):
		mod.inject(args)
	assert calls.get("cmd"), "no se invocó ningún script"
	script = Path(calls["cmd"][3]).resolve()
	assert script.parent == (REPO_ROOT / "scripts").resolve(), script


def test_claude_code_espeja_skills_kebab(tmp_path, monkeypatch):
	"""Claude Code no tenía paso de skills: ahora espeja las canónicas como
	symlinks kebab y poda los residuos (snake_case) — idempotente."""
	monkeypatch.setenv("HOME", str(tmp_path))
	repo = tmp_path / "repo"
	for rel in ("skills/scout", "skills/job-manager", "seeds/opencode/skills/frontmatter"):
		d = repo / rel
		d.mkdir(parents=True)
		(d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")

	# copias canónicas desplegadas (destinos de los symlinks)
	for rel in (".agent/skills/scout", ".agent/skills/job-manager", ".config/opencode/skills/frontmatter"):
		d = tmp_path / rel
		d.mkdir(parents=True)
		(d / "SKILL.md").write_text("x", encoding="utf-8")

	# residuo legacy + entrada ajena en el destino
	dest = tmp_path / ".claude" / "skills"
	(dest / "job_manager").mkdir(parents=True)
	(dest / "basura").mkdir()

	mod = _load("claude-code")
	assert mod._deploy_skills(str(repo)) > 0
	names = sorted(p.name for p in dest.iterdir())
	assert "job_manager" not in names  # legacy snake: se poda
	assert "basura" in names  # entrada AJENA: se respeta (red-pill es invitado)
	assert {"frontmatter", "job-manager", "scout"} <= set(names)
	assert (dest / "scout").is_symlink()
	assert mod._deploy_skills(str(repo)) == 0  # idempotente
