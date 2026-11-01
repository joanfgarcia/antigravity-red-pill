"""MinionInbox → aviso al alma por el coro (S2.1+)."""

from __future__ import annotations

from unittest.mock import patch

from red_pill.core.inbox import MinionInbox


def _inbox(tmp_path):
	return MinionInbox(db_path=str(tmp_path / "minion_inbox.db"))


def test_reporte_con_alma_publica_aviso(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice", return_value=True) as pub:
		inbox.drop_report(
			event_id="r1",
			source="OracleMinion",
			status="success",
			content="resultado listo",
			originator="oracle:1",
			continuity_id="soul-1",
		)
	pub.assert_called_once()
	kwargs = pub.call_args.kwargs
	assert kwargs["continuity_id"] == "soul-1"
	assert "OracleMinion" in kwargs["body"]
	assert "resultado listo" in kwargs["body"]


def test_reporte_sin_alma_no_publica(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice") as pub:
		inbox.drop_report(event_id="r1", source="OracleMinion", status="success", content="x")
	pub.assert_not_called()


def test_notify_false_no_publica(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice") as pub:
		inbox.drop_report(
			event_id="r1", source="JobRunner", status="success", content="x",
			continuity_id="soul-1", notify=False,
		)
	pub.assert_not_called()


def test_duplicado_no_publica_dos_veces(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice", return_value=True) as pub:
		for _ in range(2):
			inbox.drop_report(
				event_id="r1", source="OracleMinion", status="success", content="x",
				continuity_id="soul-1",
			)
	assert pub.call_count == 1


def test_jobrunner_no_usa_el_hook_generico(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice") as pub:
		inbox.drop_report(
			event_id="r1", source="JobRunner", status="success", content="x",
			continuity_id="soul-1",
		)
	pub.assert_not_called()
