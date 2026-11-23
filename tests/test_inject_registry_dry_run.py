"""`inject_cli --dry-run` no puede escribir: sólo corre el adaptador que sabe simular.

Regresión 2026-11-23: el flag sólo lo miraba pi; antigravity, claude-code y opencode
lo ignoraban y un «dry-run» reescribió CLAUDE.md, GEMINI.md y AGENTS.md en vivo.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")


def _registry():
	if SCRIPTS not in sys.path:
		sys.path.insert(0, SCRIPTS)
	spec = importlib.util.spec_from_file_location("inject_registry_under_test", os.path.join(SCRIPTS, "inject", "_registry.py"))
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_registry_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def _adapter(reg, name, calls, supports):
	def inject(args):
		calls.append(name)
		return 1

	mod = SimpleNamespace(inject=inject)
	if supports:
		mod.SUPPORTS_DRY_RUN = True
	return reg.IDEAdapter(name=name, detect_mod=SimpleNamespace(), inject_mod=mod)


def test_dry_run_omite_los_adaptadores_que_no_saben_simular():
	reg = _registry()
	calls: list[str] = []
	adapters = [_adapter(reg, "escribe", calls, False), _adapter(reg, "simula", calls, True)]
	assert reg.inject_all(argparse.Namespace(dry_run=True), adapters) == 1
	assert calls == ["simula"]


def test_sin_dry_run_corren_todos():
	reg = _registry()
	calls: list[str] = []
	adapters = [_adapter(reg, "escribe", calls, False), _adapter(reg, "simula", calls, True)]
	assert reg.inject_all(argparse.Namespace(dry_run=False), adapters) == 2
	assert calls == ["escribe", "simula"]


def test_solo_pi_declara_simulacion():
	"""Si un adaptador declara SUPPORTS_DRY_RUN debe mirar `dry_run` en su código."""
	reg = _registry()
	for adapter in reg.discover_adapters():
		src = open(os.path.join(SCRIPTS, "inject", adapter.name, "inject.py"), encoding="utf-8").read()
		if getattr(adapter.inject_mod, "SUPPORTS_DRY_RUN", False):
			assert "dry_run" in src, adapter.name
	names = {a.name for a in reg.discover_adapters() if getattr(a.inject_mod, "SUPPORTS_DRY_RUN", False)}
	assert names == {"pi"}
