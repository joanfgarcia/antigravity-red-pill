"""Latido fino en `job_list` / `job_status` (RFC-JOBDAG-002 Fase 4, cara al monitor).

El `progress` de la DB solo cambia en frontera de step: cuatro despertares seguidos
leyeron "sin latido" (o un `stage_label` viejo) mientras el hijo del DAG trabajaba.
El fichero de control sí se reescribe mientras se trabaja; aquí se prueba que el
latido que ve el monitor sale de ahí y no de la fila.
"""

from __future__ import annotations

import asyncio

from red_pill.core.progress import job_progress_age_s, write_job_progress
from red_pill.mcp_server import _fmt_beat_age, _live_progress, handle_job_list


def test_latido_solo_para_jobs_en_vuelo():
	write_job_progress("beat0001", {"label": "extract", "current": 13, "total": 42})
	assert _live_progress({"id": "beat0001", "status": "COMPLETED"}) is None
	live = _live_progress({"id": "beat0001", "status": "PROCESSING"})
	assert live["label"] == "extract" and live["current"] == 13 and live["total"] == 42
	assert isinstance(live["age_s"], float) and live["age_s"] < 60


def test_sin_fichero_no_inventa_latido():
	assert job_progress_age_s("nunca-existio") is None
	assert _live_progress({"id": "nunca-existio", "status": "PROCESSING"}) is None


def test_edad_legible():
	assert _fmt_beat_age(None) == "sin fichero"
	assert _fmt_beat_age(12) == "hace 12s"
	assert _fmt_beat_age(420) == "hace 7m"
	assert _fmt_beat_age(7200) == "hace 2.0h"


def test_job_list_pinta_el_latido(monkeypatch):
	import red_pill.mcp_server as srv

	write_job_progress("beat0002", {"label": "extract", "current": 13, "total": 42})

	class _Q:
		def list_tasks(self, **kwargs):
			return [
				{
					"id": "beat0002",
					"source": "dag_job",
					"status": "PROCESSING",
					"priority": 8,
					"mission_id": "nightly-cycle",
					"parent_task_id": None,
					"title": "Ciclo nocturno",
					"progress": {"percent": 71},
					"attempts": 0,
					"updated_at": "2026-11-03 06:53",
				}
			]

	monkeypatch.setattr(srv, "_queue", lambda: _Q())
	out = asyncio.run(handle_job_list({}))
	text = out[0].text
	assert "71%" in text  # la fila de la DB no se toca
	assert "latido beat0002: extract 13/42 · hace" in text
