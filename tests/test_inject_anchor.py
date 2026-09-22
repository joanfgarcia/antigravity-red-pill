"""Tests del target Pi en `inject_anchor.py`.

Cubren lo específico de Pi: `AGENTS.override.md` (que en Pi >=0.87 sustituye a
`AGENTS.md`/`CLAUDE.md` del mismo directorio) y el override de semillas por IDE
(`seeds/pi/anchors/<anchor>.md` gana sobre `seeds/anchors/<anchor>.md`).
"""

from __future__ import annotations

import importlib.util
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ANCHOR_PATH = os.path.join(REPO_ROOT, "scripts", "inject_anchor.py")
SEEDS_DIR = os.path.join(REPO_ROOT, "seeds", "anchors")

VARS = {"AGENT_CORE_DIR": "/tmp/ac", "RED_PILL_CMD": "rp"}


def _load() -> object:
	spec = importlib.util.spec_from_file_location("inject_anchor_under_test", ANCHOR_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_anchor_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def test_pi_target_resuelve_a_agents_override():
	m = _load()
	target = m.REGISTRY_BY_IDE["pi"]
	assert target.requires_workspace
	assert m.resolve_target_path(target, "/tmp/ws") == "/tmp/ws/AGENTS.override.md"
	assert m.resolve_target_path(target, None) is None


def test_pi_seed_override_gana_y_fallback_generico():
	m = _load()
	override = m.ide_seed_path(SEEDS_DIR, "pi", "sovereign_handshake")
	assert override.endswith(os.path.join("seeds", "pi", "anchors", "sovereign_handshake.md"))
	# Un anchor sin override cae a la semilla genérica.
	assert m.ide_seed_path(SEEDS_DIR, "pi", "agent_core") == os.path.join(SEEDS_DIR, "agent_core.md")


def test_splice_ide_pi_escribe_override_y_es_idempotente(tmp_path):
	m = _load()
	ws = str(tmp_path)
	anchors = ["sovereign_handshake", "agent_core"]
	assert m.splice_ide("pi", anchors, SEEDS_DIR, ws, VARS, backup=False) == 2
	text = open(os.path.join(ws, "AGENTS.override.md"), encoding="utf-8").read()
	assert text.count("<!-- REDPILL:BEGIN") == 2
	assert "AUTOMÁTICO en Pi" in text  # semilla pi, no la genérica MCP
	assert m.splice_ide("pi", anchors, SEEDS_DIR, ws, VARS, backup=False) == 0  # converge
