"""Fan-out por sesión del pase Memento (RFC-JOBDAG-002).

El discover debe espejar el DELTA nocturno (stale primero + tope), y `chronicle.yaml`
debe declarar el fan-out por sesión (una hoja por sesión → progreso visible).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DISCOVER = REPO / "scripts" / "list_memento_agentic_pending.py"


def _load_discover():
	spec = importlib.util.spec_from_file_location("list_memento_agentic_pending", DISCOVER)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_discover_stale_primero_y_tope():
	m = _load_discover()
	pending = [("opencode", "a", "new"), ("opencode", "b", "stale"), ("opencode", "c", "new")]
	assert m.select_targets(pending, 2) == ["opencode:b", "opencode:a"]
	assert m.select_targets(pending, 10) == ["opencode:b", "opencode:a", "opencode:c"]


def test_discover_tope_limita():
	m = _load_discover()
	pending = [("s", f"s{i}", "new") for i in range(5)]
	assert len(m.select_targets(pending, 3)) == 3


def test_chronicle_usa_fanout_por_sesion():
	cfg = yaml.safe_load((REPO / "configs" / "jobs" / "chronicle.yaml").read_text(encoding="utf-8"))
	stages = cfg["manifest"]["stages"]
	ids = [s["id"] for s in stages]
	assert "discover" in ids and "memento" in ids
	# 2026-10-30: el pase va POR FASES (una corrida de modelo por fase), no
	# intercalado por sesión — intercalado cuesta dos cambios de modelo por
	# sesión. Ambas fases comparten la lista congelada de `discover`.
	md = next(s for s in stages if s["id"] == "memento-distill")
	ma = next(s for s in stages if s["id"] == "memento-annotate")
	for etapa, fase, tarea in ((md, "distill", "distill"), (ma, "annotate", "annotate")):
		assert etapa["fan_out_from"] == "discover"
		assert f"--phase {fase} --target {{{{item}}}}" in etapa["command"]
		assert etapa["llm"]["task"] == tarea
	assert "memento-agentic" not in ids  # la etapa intercalada se retiró
	# el discover depende del migrate; el fanout del discover
	assert next(s for s in stages if s["id"] == "discover")["depends_on"] == ["memento"]
	assert md["depends_on"] == ["discover"]
	# serialización: todas las polaroids antes de empezar las notas
	assert ma["depends_on"] == ["memento-distill"]
