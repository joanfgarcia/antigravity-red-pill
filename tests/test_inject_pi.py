"""Tests del adapter Pi (scripts/inject/pi/inject.py).

Pi no soporta MCP: el injector despliega la extensión red-pill.ts en
`~/.pi/agent/extensions/` y fusiona los skills en `~/.pi/agent/skills/`
(genérico + override `seeds/pi/skills/`), sin tocar settings.json. Se ejecuta
con HOME aislado (sandbox) para no tocar el `~/.pi` real del operador.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADAPTER_PATH = os.path.join(REPO_ROOT, "scripts", "inject", "pi", "inject.py")


def _load_adapter() -> object:
	spec = importlib.util.spec_from_file_location("pi_inject_under_test", ADAPTER_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["pi_inject_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def adapter():
	return _load_adapter()


@pytest.fixture()
def sandbox_home(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	return tmp_path


def _args(**kw):
	base = dict(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False, remove=False, uv_path=None)
	base.update(kw)
	return argparse.Namespace(**base)


def test_inject_despliega_extension_y_skills(sandbox_home, adapter):
	pi_dir = sandbox_home / ".pi" / "agent"
	n = adapter.inject(_args())
	assert n > 0

	ext = pi_dir / "extensions" / "red-pill.ts"
	assert ext.exists()
	text = ext.read_text(encoding="utf-8")
	assert f'process.env.RED_PILL_DIR ?? "{REPO_ROOT}"' in text  # placeholder resuelto
	assert "${RED_PILL_DIR}" not in text

	for skill in ("job-manager", "workspace-memory", "memory-manager", "sovereign-handshake"):
		md = pi_dir / "skills" / skill / "SKILL.md"
		assert md.exists(), f"skill '{skill}' no desplegado"
		assert "${RED_PILL_CMD}" not in md.read_text(encoding="utf-8")  # invocación resuelta

	# No toca settings.json
	assert not (pi_dir / "settings.json").exists()


def test_inject_idempotente(sandbox_home, adapter):
	adapter.inject(_args())
	assert adapter.inject(_args()) == 0  # segunda pasada sin cambios


def test_inject_prunea_legados_snake_case(sandbox_home, adapter):
	pi_dir = sandbox_home / ".pi" / "agent"
	legacy = pi_dir / "skills" / "job_manager"
	legacy.mkdir(parents=True)
	(legacy / "SKILL.md").write_text("---\nname: job_manager\ndescription: x\n---\n", encoding="utf-8")
	adapter.inject(_args())
	assert not legacy.exists()  # legado pruned
	assert (pi_dir / "skills" / "job-manager" / "SKILL.md").exists()


def test_remove_borra_extension_y_skills(sandbox_home, adapter):
	adapter.inject(_args())
	removed = adapter.inject(_args(remove=True))
	assert removed > 0
	pi_dir = sandbox_home / ".pi" / "agent"
	assert not (pi_dir / "extensions" / "red-pill.ts").exists()
	assert not (pi_dir / "skills" / "job-manager").exists()
