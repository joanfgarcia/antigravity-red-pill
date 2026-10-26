"""RFC-INTEROP-003 S3.3 — línea [JOBS] en el despertar."""

from __future__ import annotations

import importlib.util
from pathlib import Path

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


def _wake_module():
	path = Path(__file__).resolve().parents[1] / "scripts" / "wake_up_v6.py"
	spec = importlib.util.spec_from_file_location("wake_up_v6_p3_test", path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class _FakeQueue:
	def __init__(self, tasks):
		self.tasks = tasks

	def list_tasks(self, *, continuity_id, limit=50):
		assert continuity_id == CID
		return self.tasks[:limit]


def test_jobs_line_lists_soul_jobs_without_auto_resume():
	wake = _wake_module()
	line = wake._jobs_block(
		CID,
		_FakeQueue(
			[
				{"id": "abcdef123456", "source": "dag_job", "status": "PAUSED", "parent_mission_id": "repo:next"},
				{"id": "123456abcdef", "source": "agentic_job", "status": "PENDING", "mission_id": "forge:x"},
			]
		),
	)
	assert line.startswith("[JOBS] 2 job(s)")
	assert "abcdef12 dag_job PAUSED (repo:next)" in line
	assert "Reanudar es explícito (job_resume)" in line


def test_jobs_line_is_silent_without_soul_or_jobs():
	wake = _wake_module()
	assert wake._jobs_block("", _FakeQueue([])) == ""
	assert wake._jobs_block(CID, _FakeQueue([])) == ""
