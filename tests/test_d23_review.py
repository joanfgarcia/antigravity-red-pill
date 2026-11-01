"""D23-SCORE v0.1 — auto-revisor: modos, prompt, enqueue y MCP."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from red_pill.session import d23_review
from red_pill.session.store import SessionRegistry


def _note(reg: SessionRegistry, mission: str = "repo:x", author: str = "alma-author"):
	return reg.add_event(
		event_type="intent_updated",
		mission_id=mission,
		summary="nota original",
		continuity_id=author,
	)


def _decision():
	return {
		"decision_id": "d1",
		"claim": "el dato no cuadra",
		"evidence": "fuente X",
		"severity": "low",
		"proposed_action": "flag",
		"created_by": "alma-obj",
		"mission_id": "repo:x",
		"requires_operator": False,
		"state": "open",
		"subject_event_id": "n1",
	}


async def _call(name: str, arguments: dict) -> str:
	from red_pill.mcp_server import handle_call_tool

	return (await handle_call_tool(name, arguments))[0].text


def test_build_prompt_por_modo():
	decision = _decision()
	note = {"summary": "nota original", "ref": "abc", "continuity_id": "alma-author"}
	review = d23_review.build_prompt(decision, note, "review")
	semi = d23_review.build_prompt(decision, note, "semi")
	auto = d23_review.build_prompt(decision, note, "auto")
	assert "suggest_review" in review and "Operador" in review
	assert "review_decision" in semi and "escalate" in semi and "high/retract" in semi
	assert "review_decision" in auto and "SIEMPRE" in auto and "escalate" in auto and "high/retract" in auto
	for text in (review, semi, auto):
		assert "d1" in text and "el dato no cuadra" in text
		assert "alma-obj" in text and "alma-author" in text
		assert "reason" in text
	assert "confidence" in semi and "confidence" in auto


async def test_mcp_review_decision_exige_reason():
	out = await _call("review_decision", {"decision_id": "d1", "action": "dismiss"})
	assert "reason" in out and "obligatorio" in out


async def test_mcp_suggest_review_exige_reason():
	out = await _call("suggest_review", {"decision_id": "d1", "verdict": "dismiss", "confidence": "high"})
	assert "reason" in out and "obligatorio" in out


def test_suggest_review_no_muta_y_aparece_en_bandeja(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	decision = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")

	with pytest.raises(ValueError, match="objetor"):
		reg.suggest_review(decision["decision_id"], reviewer_continuity_id="alma-obj", verdict="dismiss", confidence="high")
	with pytest.raises(ValueError, match="autor"):
		reg.suggest_review(decision["decision_id"], reviewer_continuity_id="alma-author", verdict="dismiss", confidence="high")

	suggestion = reg.suggest_review(
		decision["decision_id"],
		reviewer_continuity_id="alma-rev",
		verdict="dismiss",
		confidence="high",
		reason="no procede",
	)
	assert suggestion["verdict"] == "dismiss"
	assert reg.get_decision(decision["decision_id"])["state"] == "open"
	row = reg.list_decisions()[0]
	assert row["suggested_verdict"] == "dismiss"
	assert row["suggestion_confidence"] == "high"
	assert row["suggestion_reason"] == "no procede"
	assert [e["type"] for e in reg.fetch_events("repo:x")] == ["intent_updated"]


def test_suggest_review_permite_escalated(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	decision = reg.open_decision(subject_event_id=note["event_id"], claim="grave", created_by="alma-obj", severity="high")
	assert decision["state"] == "escalated"
	reg.suggest_review(decision["decision_id"], reviewer_continuity_id="alma-rev", verdict="uphold", confidence="medium")
	row = reg.list_decisions()[0]
	assert row["state"] == "escalated"
	assert row["suggested_verdict"] == "uphold"


def test_register_review_job_en_bandeja(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	decision = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")
	reg.register_review_job(decision["decision_id"], job_id="job-1", reviewer_continuity_id="alma-rev", mode="review")
	row = reg.list_decisions()[0]
	assert row["review_job_id"] == "job-1"
	assert row["review_mode"] == "review"
	assert row["reviewer"] == "alma-rev"


async def test_mcp_suggest_review(tmp_path):
	reg = SessionRegistry()
	note = _note(reg)
	decision = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")

	async def fake_session(_args):
		return {"continuity_id": "alma-rev", "originator": "opencode:rev", "mission_id": "repo:x"}

	with patch("red_pill.mcp_server._caller_session", new=fake_session):
		out = await _call(
			"suggest_review",
			{"decision_id": decision["decision_id"], "verdict": "uphold", "confidence": "medium", "reason": "ok"},
		)
	assert "SUGGEST" in out and "uphold/medium" in out
	row = reg.list_decisions()[0]
	assert row["suggested_verdict"] == "uphold"


async def test_post_encola_review(tmp_path):
	reg = SessionRegistry()
	reg.upsert_session(originator="opencode:d23a", continuity_id="alma-d23a", mission_id="repo:feat/d23")
	bridge = {"originator": "opencode:d23a", "workdir": str(tmp_path)}

	def fake_enqueue(_decision, _note, _mode):
		return "job-1"

	with (
		patch("red_pill.mcp_server._harness_bridge", return_value=bridge),
		patch("red_pill.mcp_server._current_git_branch", return_value="feat/d23"),
		patch("red_pill.session.d23_review.review_mode", return_value="review"),
		patch("red_pill.session.d23_review.enqueue_review", new=fake_enqueue),
	):
		announced = await _call("coro_api", {"action": "post", "payload": {"summary": "nota", "type": "intent_updated"}})
		event_id = announced.split("event=")[1].split()[0].strip()
		out = await _call(
			"coro_api",
			{"action": "object", "payload": {"claim": "no cuadra", "target_event_id": event_id}},
		)
	assert "review_job=job-1" in out
	assert "mode=review" in out


def test_enqueue_review_payload_y_receta(monkeypatch):
	class FakeQueue:
		def __init__(self):
			self.kwargs = None

		def enqueue_task(self, **kwargs):
			self.kwargs = kwargs
			return "job-42"

	class FakeRegistry:
		def __init__(self):
			self.args = ()
			self.kwargs = {}
			self.session_kwargs = {}
			self.unregistered = []

		def upsert_session(self, **kwargs):
			self.session_kwargs = kwargs

		def register_review_job(self, *args, **kwargs):
			self.args = args
			self.kwargs = kwargs

		def unregister_session(self, originator):
			self.unregistered.append(originator)
			return True

	queue = FakeQueue()
	registry = FakeRegistry()
	monkeypatch.setattr(d23_review, "CognitiveQueueManager", lambda: queue)
	monkeypatch.setattr(d23_review, "SessionRegistry", lambda: registry)
	note = {"summary": "nota", "ref": "r1", "continuity_id": "alma-author"}
	decision = _decision()

	assert d23_review.enqueue_review(decision, note, "off") is None
	job_id = d23_review.enqueue_review(decision, note, "review")
	assert job_id == "job-42"
	payload = queue.kwargs["payload"]
	assert payload["continuity_id"] == d23_review.reviewer_continuity()
	assert payload["parent_mission_id"] == "repo:x"
	assert payload["originator"].startswith("d23-review:")
	assert payload["role"] == "reviewer"
	assert "suggest_review" in payload["prompt"]
	assert payload["cascade"]
	assert queue.kwargs["mission_id"] == "mission:d23-review"
	assert registry.kwargs["mode"] == "review"
	assert registry.session_kwargs["originator"] == payload["originator"]
	assert registry.session_kwargs["continuity_id"] == payload["continuity_id"]
	assert registry.session_kwargs["mission_id"] == "repo:x"
	assert registry.session_kwargs["role"] == "reviewer"


def test_revisor_asignado_y_confianza_semi(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")
	reg.register_review_job(d["decision_id"], job_id="job-1", reviewer_continuity_id="alma-rev", mode="semi")

	with pytest.raises(ValueError, match="asignado"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-otro", action="dismiss", reason="x", confidence="high")
	with pytest.raises(ValueError, match="high"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="dismiss", reason="x", confidence="medium")
	done = reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="dismiss", reason="ok", confidence="high")
	assert done["state"] == "dismissed"
	rows = reg.list_decisions(states=["dismissed"])
	assert rows and rows[0]["review_confidence"] == "high"


def test_modo_review_no_muta_y_semi_no_sugiere(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")
	reg.register_review_job(d["decision_id"], job_id="job-r", reviewer_continuity_id="alma-rev", mode="review")
	with pytest.raises(ValueError, match="suggest_review"):
		reg.review_decision(d["decision_id"], reviewer_continuity_id="alma-rev", action="dismiss", reason="x")
	reg.suggest_review(d["decision_id"], reviewer_continuity_id="alma-rev", verdict="dismiss", confidence="high", reason="x")

	reg.register_review_job(d["decision_id"], job_id="job-s", reviewer_continuity_id="alma-rev", mode="semi")
	with pytest.raises(ValueError, match="review_decision"):
		reg.suggest_review(d["decision_id"], reviewer_continuity_id="alma-rev", verdict="dismiss", confidence="high", reason="y")


def test_suggest_review_reemplaza_por_revisor(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	note = _note(reg)
	d = reg.open_decision(subject_event_id=note["event_id"], claim="duda", created_by="alma-obj")
	reg.suggest_review(d["decision_id"], reviewer_continuity_id="alma-rev", verdict="uphold", confidence="medium", reason="a")
	reg.suggest_review(d["decision_id"], reviewer_continuity_id="alma-rev", verdict="dismiss", confidence="high", reason="b")
	rows = reg.list_decisions()
	assert rows[0]["suggested_verdict"] == "dismiss"
	assert rows[0]["suggestion_confidence"] == "high"


def test_bandeja_filtra_sealed_y_ocultas(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	sealed = reg.add_event(event_type="intent_updated", mission_id="repo:x", summary="secreto", continuity_id="alma-x", sealed=True)
	reg.open_decision(subject_event_id=sealed["event_id"], claim="x", created_by="alma-obj")
	assert reg.list_decisions() == []

	visible = _note(reg)
	reg.open_decision(subject_event_id=visible["event_id"], claim="y", created_by="alma-obj")
	reg._set_note_status(visible["event_id"], "repo:x", "hidden", "operator", "spam")
	assert reg.list_decisions() == []


async def test_object_rechaza_nota_sealed(tmp_path):
	reg = SessionRegistry()
	reg.upsert_session(originator="opencode:d23a", continuity_id="alma-d23a", mission_id="repo:feat/d23")
	bridge = {"originator": "opencode:d23a", "workdir": str(tmp_path)}
	with (
		patch("red_pill.mcp_server._harness_bridge", return_value=bridge),
		patch("red_pill.mcp_server._current_git_branch", return_value="feat/d23"),
	):
		sealed = await _call("coro_api", {"action": "post", "payload": {"summary": "secreto", "type": "intent_updated", "sealed": True}})
		event_id = sealed.split("event=")[1].split()[0].strip()
		out = await _call("coro_api", {"action": "object", "payload": {"claim": "obj", "target_event_id": event_id}})
	assert "sealed" in out


def test_cli_moderate_requiere_operador(monkeypatch, capsys):
	from argparse import Namespace

	from red_pill.cli_services import handle_session

	reg = SessionRegistry()
	note = reg.add_event(event_type="intent_updated", mission_id="repo:x", summary="cli", continuity_id="alma-x")
	args = Namespace(session_cmd="moderate", event_id=note["event_id"], action="hide", reason="test", json=False)
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	handle_session(args)
	assert "solo Operador" in capsys.readouterr().out
	monkeypatch.setenv("REDPILL_OPERATOR", "1")
	handle_session(args)
	out = capsys.readouterr().out
	assert "[MODERATE]" in out and "hidden" in out


def test_enqueue_review_skip_sealed(monkeypatch):
	class FakeQueue:
		def __init__(self):
			self.kwargs = None

		def enqueue_task(self, **kwargs):
			self.kwargs = kwargs
			return "x"

	class FakeRegistry:
		def upsert_session(self, **kwargs):
			return None

		def register_review_job(self, *args, **kwargs):
			return None

		def unregister_session(self, originator):
			return True

	queue = FakeQueue()
	registry = FakeRegistry()
	monkeypatch.setattr(d23_review, "CognitiveQueueManager", lambda: queue)
	monkeypatch.setattr(d23_review, "SessionRegistry", lambda: registry)
	assert d23_review.enqueue_review(_decision(), {"summary": "sealed", "sealed": True}, "auto") is None
	assert queue.kwargs is None


def test_enqueue_review_skip_hidden(monkeypatch):
	class FakeQueue:
		def __init__(self):
			self.kwargs = None

		def enqueue_task(self, **kwargs):
			self.kwargs = kwargs
			return "x"

	class FakeRegistry:
		def upsert_session(self, **kwargs):
			return None

		def register_review_job(self, *args, **kwargs):
			return None

		def get_note_status(self, event_id):
			return "hidden"

	queue = FakeQueue()
	registry = FakeRegistry()
	monkeypatch.setattr(d23_review, "CognitiveQueueManager", lambda: queue)
	monkeypatch.setattr(d23_review, "SessionRegistry", lambda: registry)
	assert d23_review.enqueue_review(_decision(), {"summary": "h", "event_id": "n1"}, "auto") is None
	assert queue.kwargs is None


def test_enqueue_review_orphan_leg_cleanup(monkeypatch):
	class FakeQueue:
		def enqueue_task(self, **kwargs):
			raise RuntimeError("queue down")

	class FakeRegistry:
		def __init__(self):
			self.unregistered = []

		def upsert_session(self, **kwargs):
			return None

		def register_review_job(self, *args, **kwargs):
			return None

		def unregister_session(self, originator):
			self.unregistered.append(originator)
			return True

	registry = FakeRegistry()
	monkeypatch.setattr(d23_review, "CognitiveQueueManager", lambda: FakeQueue())
	monkeypatch.setattr(d23_review, "SessionRegistry", lambda: registry)
	assert d23_review.enqueue_review(_decision(), {"summary": "x"}, "auto") is None
	assert registry.unregistered == ["d23-review:d1"]
