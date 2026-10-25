"""D23-SCORE v0 — objeciones + D-obj, sin votos ni retirada automática.

Contrato: una objeción abre una decisión dinámica; un revisor independiente
puede uphold (flag) / dismiss / escalate; el Operador decide hide/retract/
restore. Nada se borra; `hidden/retracted` se filtra del tablón salvo para su
autor o el Operador.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from red_pill.session.store import SessionRegistry


@pytest.fixture
def reg(tmp_path):
	return SessionRegistry(str(tmp_path / "session.db"))


def _note(reg, mission="repo:x", author="alma-author"):
	return reg.add_event(
		event_type="intent_updated",
		mission_id=mission,
		summary="nota original",
		continuity_id=author,
	)


def test_open_decision_idempotent_y_alta_severidad_escala(reg):
	note = _note(reg)
	first = reg.open_decision(subject_event_id=note["event_id"], claim="dato erróneo", created_by="alma-obj")
	assert first["state"] == "open" and first["requires_operator"] is False and first["created"] is True
	again = reg.open_decision(subject_event_id=note["event_id"], claim="otra vez", created_by="alma-obj")
	assert again["decision_id"] == first["decision_id"] and again["created"] is False

	high = reg.open_decision(
		subject_event_id=note["event_id"],
		claim="identidad falsa",
		created_by="alma-otra",
		severity="high",
		proposed_action="retract",
	)
	assert high["state"] == "escalated" and high["requires_operator"] is True


def test_revisor_independiente_aplica_flag_y_no_puede_auto_revisarse(reg):
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")

	with pytest.raises(ValueError, match="objetor"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-obj", action="uphold")
	with pytest.raises(ValueError, match="autor"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-author", action="uphold")

	done = reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="uphold", reason="confirmado")
	assert done["state"] == "upheld"
	assert reg.get_note_status(note["event_id"]) == "flagged"
	events = reg.fetch_events("repo:x", viewer_continuity_id="alma-otro")
	assert events[0]["note_status"] == "flagged"
	assert events[0]["open_decisions"] == 0


def test_alta_severidad_no_la_cierra_un_agente(reg):
	note = _note(reg)
	d = reg.open_decision(
		subject_event_id=note["event_id"], claim="retirar", created_by="alma-obj", severity="high"
	)
	with pytest.raises(ValueError, match="Operador"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="dismiss")
	escalated = reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="escalate")
	assert escalated["state"] == "escalated"


def test_ttl_escala_sin_ocultar(reg):
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="sin revisor", created_by="alma-obj", ttl_h=0)
	assert d["state"] == "open"
	pending = reg.list_decisions()
	assert pending and pending[0]["state"] == "escalated"
	assert reg.get_note_status(note["event_id"]) == "visible"


def test_operador_oculta_y_restaura(reg):
	note = _note(reg)
	reg.open_decision(subject_event_id=note["event_id"], claim="spam", created_by="alma-obj")
	hidden = reg.moderate_note(note["event_id"], action="hide", actor="operator", reason="spam")
	assert hidden["status"] == "hidden"
	assert hidden["resolved_decisions"] == 1

	assert reg.fetch_events("repo:x", viewer_continuity_id="alma-otro") == []
	assert len(reg.fetch_events("repo:x", viewer_continuity_id="alma-author")) == 1
	assert len(reg.fetch_events("repo:x", viewer_continuity_id="alma-otro", include_hidden=True)) == 1

	reg.moderate_note(note["event_id"], action="restore", actor="operator", reason="falsa alarma")
	assert reg.get_note_status(note["event_id"]) == "visible"
	assert len(reg.fetch_events("repo:x", viewer_continuity_id="alma-otro")) == 1


def test_bandeja_pone_primero_lo_que_requiere_operador(reg):
	note = _note(reg)
	reg.open_decision(subject_event_id=note["event_id"], claim="bajo", created_by="alma-1")
	reg.open_decision(subject_event_id=note["event_id"], claim="alto", created_by="alma-2", severity="high")
	rows = reg.list_decisions()
	assert [row["requires_operator"] for row in rows] == [True, False]
	assert rows[0]["note_summary"] == "nota original"


def test_eventos_internos_no_ensucian_el_tablon(reg):
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="x", created_by="alma-obj")
	reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="dismiss")
	events = reg.fetch_events("repo:x")
	assert [e["type"] for e in events] == ["intent_updated"]
	assert reg.count_events("repo:x") == 1


# ── MCP ───────────────────────────────────────────────────────────────────────
def _bridge(originator: str, workdir: str) -> dict:
	return {"originator": originator, "workdir": workdir}


async def _call(name, arguments):
	from red_pill.mcp_server import handle_call_tool

	return (await handle_call_tool(name, arguments))[0].text


async def test_mcp_objection_abre_dobj_y_fetch_la_marca(tmp_path):
	reg = SessionRegistry()
	reg.upsert_session(
		originator="opencode:d23a",
		continuity_id="alma-d23a",
		mission_id="repo:feat/d23",
	)
	bridge = _bridge("opencode:d23a", str(tmp_path))
	with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
		with patch("red_pill.mcp_server._current_git_branch", return_value="feat/d23"):
			announced = await _call("announce_intent", {"summary": "nota a revisar", "type": "intent_updated"})
			event_id = announced.split("event=")[1].split()[0].strip()
			out = await _call(
				"announce_intent",
				{
					"summary": "el dato no cuadra",
					"type": "objection",
					"target_event_id": event_id,
					"severity": "low",
					"proposed_action": "flag",
				},
			)
			fetched = await _call("fetch_events", {})
	assert "OBJECTION" in out and "state=open" in out
	assert "[disputed:1]" in fetched

	inbox = await _call("list_decisions", {})
	assert "DECISIONES" in inbox and "el dato no cuadra" not in inbox
	assert "nota a revisar" in inbox

	# Revisor independiente vía MCP (identidad simulada).
	async def fake_session(_args):
		return {"continuity_id": "alma-rev", "originator": "opencode:rev", "mission_id": "repo:feat/d23"}

	with patch("red_pill.mcp_server._caller_session", new=fake_session):
		review = await _call("review_decision", {"decision_id": out.split("decision=")[1].split()[0].strip(), "action": "dismiss", "reason": "no procede"})
	assert "→ dismissed" in review


async def test_mcp_moderate_requiere_operador(tmp_path, monkeypatch):
	note = SessionRegistry().add_event(
		event_type="intent_updated", mission_id="repo:feat/d23", summary="nota", continuity_id="alma-x"
	)
	denied = await _call("moderate_note", {"event_id": note["event_id"], "action": "hide"})
	assert "solo Operador" in denied

	monkeypatch.setenv("REDPILL_OPERATOR", "1")
	ok = await _call("moderate_note", {"event_id": note["event_id"], "action": "hide", "reason": "test"})
	assert "→ hidden" in ok


def test_decision_create_devuelve_sin_revisar_si_no_hay_alma():
	# Guard directo del store (el handler MCP exige continuity): sin soul no hay revisor.
	reg = SessionRegistry()
	note = reg.add_event(event_type="intent_updated", mission_id="m", summary="n", continuity_id="a")
	d = reg.open_decision(subject_event_id=note["event_id"], claim="c", created_by="b")
	with pytest.raises(ValueError):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="", action="uphold")
