"""`_report_job` avisa por el coro y cae al push directo si el buzón no está."""

from __future__ import annotations

from unittest.mock import patch

from red_pill.core.queue_worker import _report_job

TASK = {
	"source": "script_job",
	"mission_id": "repo:test",
	"payload": {"title": "CI", "parent_mission_id": "repo:test"},
}


def test_reporte_de_job_usa_el_coro_y_no_duplica_inbox():
	with (
		patch("red_pill.jobs.artifacts.job_identity", return_value={"continuity_id": "soul-1", "originator": "job:abc"}),
		patch("red_pill.jobs.artifacts.write_job_result", return_value={"paths": {"state_json": "/tmp/r.json"}}),
		patch("red_pill.core.inbox.MinionInbox") as inbox_cls,
		patch("red_pill.coro.notify.publish_notice", return_value=True) as publish,
		patch("red_pill.core.soul_notify.notify_soul") as notify,
	):
		_report_job("job123", TASK, "success", "ok")
	drop = inbox_cls.return_value.drop_report
	assert drop.call_args.kwargs["notify"] is False
	publish.assert_called_once()
	assert publish.call_args.kwargs["continuity_id"] == "soul-1"
	assert publish.call_args.kwargs["mission_id"] == "repo:test"
	assert "ok" in publish.call_args.kwargs["body"]
	notify.assert_not_called()


def test_si_el_coro_no_esta_cae_al_push_directo():
	with (
		patch("red_pill.jobs.artifacts.job_identity", return_value={"continuity_id": "soul-1", "originator": "job:abc"}),
		patch("red_pill.jobs.artifacts.write_job_result", return_value={"paths": {"state_json": "/tmp/r.json"}}),
		patch("red_pill.core.inbox.MinionInbox"),
		patch("red_pill.coro.notify.publish_notice", return_value=False),
		patch("red_pill.core.soul_notify.notify_soul") as notify,
	):
		_report_job("job123", TASK, "success", "ok")
	notify.assert_called_once()
	assert notify.call_args.args[0] == "soul-1"
