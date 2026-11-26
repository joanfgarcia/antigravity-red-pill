"""ETA honesto del dag_job y «degradado total» = fallo.

Casos reales que originan estos tests:
- `6028d497` (ciclo nocturno): un step de fan-out de 1.673 s multiplicado por las
  21 etapas restantes anunció 9 h 46 min para un ciclo de ~1 h.
- `07fca254` (bonsai_eval): 12/12 etapas degradadas por `on_fail: warn` y el job
  se selló como `success`.
Ver `.red-pill/memory/NOTE_2026-11-25_eta-job-manager.md` y
`NOTE_2026-11-25_dag-etapas-degradadas.md`.
"""

from __future__ import annotations

import pytest

from red_pill.core import progress as prog
from red_pill.jobs.drivers import update_step_ema
from red_pill.jobs.drivers.dag_manifest import _all_leaves_degraded


def test_ema_hereda_del_step_anterior():
	first = update_step_ema({"current": 1, "total": 4}, 600)
	assert first["step_seconds_ema"] == 600

	# Sin `previous` la EMA ES el último valor (el defecto que veíamos en producción)
	suelto = update_step_ema({"current": 2, "total": 4}, 1800)
	assert suelto["step_seconds_ema"] == 1800

	# Con `previous` sí suaviza (alpha 0.3): 0.3*1800 + 0.7*600 = 960
	suave = update_step_ema({"current": 2, "total": 4}, 1800, previous={"step_seconds_ema": 600})
	assert suave["step_seconds_ema"] == 960
	assert suave["eta_seconds"] == 1920


def test_override_manda_y_none_suprime_el_numero():
	# El DAG decide «no hay número honesto» mientras corre un fan-out.
	sin_numero = update_step_ema({"current": 3, "total": 24, "eta_seconds_override": None}, 60, previous={"step_seconds_ema": 1673})
	assert "eta_seconds" not in sin_numero
	assert "eta_seconds_override" not in sin_numero  # no se filtra al usuario

	con_numero = update_step_ema({"current": 3, "total": 24, "eta_seconds_override": 420}, 60)
	assert con_numero["eta_seconds"] == 420


def test_mediana_por_etapa(tmp_path, monkeypatch):
	monkeypatch.setattr(prog, "_stage_stats_path", lambda: tmp_path / "stats.json")
	prog.record_stage_durations("m1", {"a": 10, "b": 1000})
	prog.record_stage_durations("m1", {"a": 20})
	prog.record_stage_durations("m2", {"a": 99})

	med = prog.stage_duration_medians("m1")
	assert med["a"] == 15  # mediana de [10, 20]
	assert med["b"] == 1000
	assert prog.stage_duration_medians("m2")["a"] == 99


def test_historial_no_crece_sin_limite(tmp_path, monkeypatch):
	monkeypatch.setattr(prog, "_stage_stats_path", lambda: tmp_path / "stats.json")
	for value in range(1, 41):
		prog.record_stage_durations("m", {"a": value})
	raw = prog._read_stage_stats()["m"]["a"]
	assert len(raw) == prog.STAGE_STATS_HISTORY
	assert raw[-1] == 40


def test_degradado_total_es_fallo():
	stages = [
		{"id": "ctx-q8", "type": "command"},
		{"id": "comp", "type": "compound", "sub_etapas": [{"id": "bench", "type": "command"}]},
	]
	assert _all_leaves_degraded(stages, {"ctx-q8": "boom", "comp/bench": "boom"})
	assert not _all_leaves_degraded(stages, {"ctx-q8": "boom"})  # parcial: no
	assert not _all_leaves_degraded(stages, {})


@pytest.mark.parametrize("override", [None, 0])
def test_override_nunca_llega_al_progreso_publicado(override):
	out = update_step_ema({"current": 1, "total": 2, "eta_seconds_override": override}, 5)
	assert "eta_seconds_override" not in out
