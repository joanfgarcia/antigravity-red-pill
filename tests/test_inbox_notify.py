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


def test_aviso_lleva_titular_y_no_el_cuerpo_entero(tmp_path):
	"""Un dossier de 6 fragmentos no debe viajar entero al coro (2026-11-26)."""
	inbox = _inbox(tmp_path)
	content = (
		"ORACLE CONTEXT (raw) — 6 fragmento(s)\n"
		"query: q\n\n"
		"## work_memories\n"
		"- #1 · cos 0.423 · id=9852c213 · 2026-11-10\n  cuerpo largo del engrama"
	)
	with patch("red_pill.coro.notify.publish_notice", return_value=True) as pub:
		inbox.drop_report(
			event_id="evt-9",
			source="OracleMinion",
			status="success",
			content=content,
			continuity_id="soul-1",
		)
	body = pub.call_args.kwargs["body"]
	assert "ORACLE CONTEXT (raw)" in body
	assert "inbox evt-9" in body
	assert "cos 0.423" not in body


def test_aviso_recorta_un_titular_larguisimo(tmp_path):
	inbox = _inbox(tmp_path)
	with patch("red_pill.coro.notify.publish_notice", return_value=True) as pub:
		inbox.drop_report(
			event_id="evt-10",
			source="OracleMinion",
			status="success",
			content="x" * 500,
			continuity_id="soul-1",
		)
	body = pub.call_args.kwargs["body"]
	assert "…" in body
	assert "x" * 500 not in body
