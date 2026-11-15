"""Identidad del llamante en job_submit: ambigüedad fail-closed + auditoría.

El incidente 2026-11-08 (job MOSS atribuido a otra pestaña) es una recurrencia
del 2026-10-28: el proxy ya distingue AMBIGUO de NO-SÉ, pero el backend caía al
bridge global y heredaba el alma del último escritor. Estos tests fijan el
contrato: el proxy marca `ambiguous`, `job_submit` falla cerrado y la cola
registra `origin_session_id`/`submitted_by`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import red_pill.mcp_server as mcp_server
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.artifacts import job_identity


def _fake_queue():
	queue = MagicMock()
	queue.enqueue_task.return_value = "job-test-1"
	return queue


@pytest.mark.asyncio
async def test_job_submit_rejects_ambiguous_caller(monkeypatch):
	async def fake_session(_args):
		return {
			"originator": "opencode:ses_other",
			"continuity_id": "soul-other",
			"mission_id": "repo:sharing",
			"role": "task",
			"proxy_ambiguous": True,
		}

	queue = _fake_queue()
	monkeypatch.setattr(mcp_server, "_caller_session", fake_session)
	monkeypatch.setattr(mcp_server, "_queue", lambda: queue)
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)

	result = await mcp_server.handle_job_submit(
		{"source": "script_job", "payload": {"step_command": ["true"]}}
	)
	text = result[0].text
	assert "ambigua" in text.lower()
	assert "continuity" in text.lower()
	queue.enqueue_task.assert_not_called()


@pytest.mark.asyncio
async def test_job_submit_records_caller_audit_fields(monkeypatch):
	async def fake_session(_args):
		return {
			"originator": "opencode:ses_e435f5d63ffeR4eLFyO8Hl0rC6",
			"continuity_id": "soul-1",
			"mission_id": "repo:sharing",
			"role": "task",
			"proxy_ambiguous": False,
		}

	queue = _fake_queue()
	monkeypatch.setattr(mcp_server, "_caller_session", fake_session)
	monkeypatch.setattr(mcp_server, "_queue", lambda: queue)
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)

	result = await mcp_server.handle_job_submit(
		{"source": "script_job", "payload": {"step_command": ["true"]}}
	)
	assert "[OK]" in result[0].text
	payload = queue.enqueue_task.call_args.kwargs["payload"]
	assert payload["continuity_id"] == "soul-1"
	assert payload["parent_mission_id"] == "repo:sharing"
	assert payload["origin_session_id"] == "ses_e435f5d63ffeR4eLFyO8Hl0rC6"
	assert payload["submitted_by"] == "mcp:opencode:ses_e435f5d63ffeR4eLFyO8Hl0rC6"


def test_queue_persists_audit_fields(tmp_path):
	queue = CognitiveQueueManager(db_path=str(tmp_path / "queue.db"))
	job_id = queue.enqueue_task(
		source="script_job",
		payload={
			"step_command": ["true"],
			"origin_session_id": "ses_x",
			"submitted_by": "mcp:opencode:ses_x",
		},
		priority=5,
		mission_id="media-moss-eval",
	)
	row = queue.get_task(job_id)
	assert row is not None
	assert row["origin_session_id"] == "ses_x"
	assert row["submitted_by"] == "mcp:opencode:ses_x"


def test_job_identity_includes_provenance():
	identity = job_identity(
		{
			"continuity_id": "soul-1",
			"parent_mission_id": "repo:sharing",
			"origin_session_id": "ses_x",
			"submitted_by": "mcp:opencode:ses_x",
			"payload": {},
		}
	)
	assert identity["origin_session_id"] == "ses_x"
	assert identity["submitted_by"] == "mcp:opencode:ses_x"
