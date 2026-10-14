"""Fase 4 (RFC-JOBDAG-002): avance fino intra-etapa FUERA de la DB.

El job publica su progreso en un fichero de control; `job list` lo lee SOLO para
los PROCESSING (como `stage_*`) y sirve de forense. Sin threading ni escrituras DB.
"""

from __future__ import annotations

from red_pill import cli
from red_pill.jobs.drivers.base import job_progress_path, read_job_progress, write_job_progress
from red_pill.jobs.drivers.dag import DagJobDriver


def test_progress_file_roundtrip(tmp_path):
	write_job_progress("abcdef12", {"label": "sesión", "current": 3, "total": 9})
	assert job_progress_path("abcdef12").is_file()
	assert read_job_progress("abcdef12") == {"label": "sesión", "current": 3, "total": 9}
	assert read_job_progress("no-existe") is None


def test_cli_merge_solo_processing():
	write_job_progress("proc0001", {"label": "sesión", "current": 4, "total": 10})
	prog = cli._progress_display({"id": "proc0001", "status": "PROCESSING", "progress": {"current": 2, "total": 5, "percent": 40}})
	assert prog["stage_label"] == "sesión" and prog["stage_current"] == 4 and prog["stage_total"] == 10
	assert prog["current"] == 2  # el contador de la DB no se toca

	write_job_progress("done0001", {"label": "x", "current": 1, "total": 2})
	prog2 = cli._progress_display({"id": "done0001", "status": "COMPLETED", "progress": {"current": 1, "total": 2}})
	assert "stage_label" not in prog2  # no-PROCESSING ignora el fichero


def test_dag_inyecta_rp_progress_file(tmp_path, monkeypatch):
	record = []

	class _Cmd:
		async def execute(self, task, **kwargs):
			record.append((task, kwargs))
			return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}

	import red_pill.jobs.drivers.dag as dag
	import red_pill.swarm.factory as fac

	monkeypatch.setattr(fac.MinionFactory, "create", staticmethod(lambda mid, **kw: _Cmd()))
	monkeypatch.setattr(dag, "_resolve_minion_kind", lambda mid: "command")

	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	d = DagJobDriver()
	d.bind("job-progress-1")
	payload = {
		"mission_id": "m",
		"manifest": {
			"workdir": str(ws),
			"stages": [
				{"id": "long", "type": "command", "minion": "command_runner", "command": "x", "progress_file": True},
			],
		},
	}
	d.step(payload, {})
	env = record[0][1].get("env") or {}
	assert "RP_PROGRESS_FILE" in env and env["RP_PROGRESS_FILE"].endswith(".progress.json")
