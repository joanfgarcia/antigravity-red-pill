"""B-02 — servicio de compactación: umbrales, corte seguro y reset."""

from __future__ import annotations

import pytest

from red_pill.session.compactor import (
	CompactionError,
	Compactor,
	estimate_messages_tokens,
	is_context_length_error,
)
from red_pill.session.mirror import SessionMirror
from red_pill.session.summarizer import ExtractiveSummarizer


@pytest.fixture
def mirror(tmp_path):
	return SessionMirror(str(tmp_path / "session.db"))


class FakeSummarizer:
	name = "fake"

	def __init__(self, text="## Estado\nresumen", fail=False):
		self.text = text
		self.fail = fail
		self.seen: list[str] = []

	def summarize(self, *, text, instructions=None, max_tokens=600):
		self.seen.append(text)
		if self.fail:
			raise RuntimeError("model down")
		return self.text


def _seed(mirror, n=8, continuity="alma-1"):
	for i in range(1, n + 1):
		mirror.append_turn(
			continuity_id=continuity,
			mission_id="repo:next",
			role="user" if i % 2 else "assistant",
			content=f"turno {i}",
			source_ref=f"t{i}",
			ts=float(i),
		)


def test_estimate_counts_content_and_tool_calls():
	messages = [
		{"role": "user", "content": "x" * 32},
		{"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": "{}"}}]},
	]
	assert estimate_messages_tokens(messages) >= 11


def test_context_under_budget_does_not_compact(mirror):
	_seed(mirror, 3)
	summarizer = FakeSummarizer()
	compactor = Compactor(mirror, summarizer=summarizer, protect_last_n=1)
	ctx = compactor.ensure_context("alma-1", budget_tokens=8000)
	assert ctx.compacted is False
	assert summarizer.seen == []
	assert len(ctx.turns) == 3


def test_ensure_context_compacts_and_protects_tail(mirror):
	_seed(mirror, 8)
	summarizer = FakeSummarizer()
	compactor = Compactor(mirror, summarizer=summarizer, protect_last_n=2)
	ctx = compactor.ensure_context("alma-1", budget_tokens=20, reserve_tokens=10)
	assert ctx.compacted is True
	assert [t["content"] for t in ctx.turns] == ["## Estado\nresumen", "turno 7", "turno 8"]
	assert "turno 1" in summarizer.seen[0] and "turno 4" in summarizer.seen[0]
	assert "turno 7" not in summarizer.seen[0]
	assert mirror.latest_compaction("alma-1")["range_end_seq"] == 6


def test_safe_cut_never_splits_tool_pair(mirror):
	_seed(mirror, 4)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:next",
		role="assistant",
		content=None,
		tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
		source_ref="a-call",
	)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:next",
		role="tool",
		content="resultado",
		tool_call_id="call_1",
		source_ref="a-result",
	)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=2)
	done = compactor.compact_now("alma-1")
	assert done["range_end_seq"] == 4
	ctx = compactor.context("alma-1")
	assert [t["role"] for t in ctx.turns] == ["system", "assistant", "tool"]
	assert ctx.turns[1]["tool_calls"][0]["id"] == "call_1"
	assert ctx.turns[2]["tool_call_id"] == "call_1"


def test_compact_now_no_range_is_noop(mirror):
	_seed(mirror, 2)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=2)
	assert compactor.compact_now("alma-1") is None


def test_failed_summary_aborts_and_preserves_context(mirror):
	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(fail=True), protect_last_n=1)
	with pytest.raises(CompactionError):
		compactor.compact_now("alma-1")
	assert mirror.latest_compaction("alma-1") is None
	rows = mirror.compactions("alma-1")
	assert len(rows) == 1 and rows[0]["status"] == "aborted"
	assert "model down" in rows[0]["reason"]
	assert len(mirror.context_turns("alma-1")) == 6


def test_second_compaction_keeps_parent(mirror):
	_seed(mirror, 10)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("uno"), protect_last_n=1)
	first = compactor.compact_now("alma-1")
	for i in (11, 12):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"t{i}")
	second = compactor.compact_now("alma-1", mission_id="repo:next")
	assert first is not None and second is not None
	assert second["parent_compaction_id"] == first["compaction_id"]
	assert mirror.latest_compaction("alma-1")["compaction_id"] == second["compaction_id"]


def test_reset_leaves_only_handoff_context(mirror):
	_seed(mirror, 5)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=1)
	done = compactor.reset("alma-1", summary="## Handoff\nseguir", mission_id="repo:next")
	assert done["range_start_seq"] == 0 and done["range_end_seq"] == 5
	ctx = compactor.context("alma-1")
	assert [t["content"] for t in ctx.turns] == ["## Handoff\nseguir"]


def test_maybe_compact_returns_reduced_messages(mirror):
	_seed(mirror, 8)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=2)
	messages = mirror.context_messages("alma-1")
	out = compactor.maybe_compact("alma-1", messages, threshold=10)
	assert len(out) == 3
	assert out[0]["content"] == "## Estado\nresumen"


def test_extractive_is_a_valid_default(mirror):
	_seed(mirror, 4)
	compactor = Compactor(mirror, summarizer=ExtractiveSummarizer(), protect_last_n=1)
	done = compactor.compact_now("alma-1")
	assert done is not None and "Resumen extractivo" in done["summary"]


def test_mini_session_compacts_before_provider(tmp_path):
	from red_pill.mini.session import MiniConfig, MiniSession

	class Provider:
		def __init__(self):
			self.calls = []

		def chat(self, messages, **kwargs):
			self.calls.append(list(messages))
			return {"role": "assistant", "content": "ok"}

	mirror = SessionMirror(str(tmp_path / "session.db"))
	_seed(mirror, 8)
	provider = Provider()
	cfg = MiniConfig(
		workspace=str(tmp_path),
		continuity_id="alma-1",
		mission_id="repo:next",
		db_path=str(tmp_path / "session.db"),
		context_tokens=20,
		compactor_enabled=True,
		compactor_engine="extractive",
		compactor_protect_last_n=1,
	)
	session = MiniSession(cfg, {"forge": provider})
	session.run("forge", system_prompt="You are Forge.", task="continúa", tools=None)
	first = provider.calls[0]
	assert first[0]["role"] == "system"
	assert any("Resumen extractivo" in str(m.get("content")) for m in first)
	assert not any(str(m.get("content")) == "turno 1" for m in first)
	assert session.mirror.latest_compaction("alma-1") is not None


def test_context_keeps_uncompacted_middle_gap(mirror):
	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("resumen"), protect_last_n=4)
	compactor.compact_now("alma-1")
	for i in range(3, 23):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"t{i}")
	turns = mirror.context_turns("alma-1")
	assert [t["content"] for t in turns[:2]] == ["resumen", "turno 3"]
	assert turns[-1]["content"] == "turno 22"
	assert len(turns) == 21


def test_start_same_range_is_idempotent(mirror):
	first = mirror.start_compaction(
		continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=4, compaction_id="a"
	)
	second = mirror.start_compaction(
		continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=4, compaction_id="b"
	)
	assert first["compaction_id"] == second["compaction_id"] == "a"
	assert len(mirror.compactions("alma-1")) == 1


def test_complete_aborted_is_rejected(mirror):
	_seed(mirror, 4)
	mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=2, compaction_id="c1")
	mirror.abort_compaction("c1", reason="boom")
	with pytest.raises(ValueError):
		mirror.complete_compaction("c1", summary="no")


def test_ensure_context_without_range_is_honest(mirror):
	_seed(mirror, 2)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=2)
	ctx = compactor.ensure_context("alma-1", budget_tokens=1, reserve_tokens=0)
	assert ctx.compacted is False
	assert ctx.compaction_id is None
	assert mirror.compactions("alma-1") == []


def test_large_summary_that_does_not_shrink_is_aborted(mirror):
	for i in range(1, 7):
		mirror.append_turn(
			continuity_id="alma-1",
			mission_id="m",
			role="user",
			content=("texto largo " * 80) + str(i),
			source_ref=f"long{i}",
		)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("x" * 10000), protect_last_n=1)
	with pytest.raises(CompactionError):
		compactor.compact_now("alma-1")
	rows = mirror.compactions("alma-1")
	assert rows and rows[0]["status"] == "aborted"
	assert "summary_not_smaller" in rows[0]["reason"]


def test_rehydrate_uses_compacted_context(mirror):
	from red_pill.session.switch import rehydrate_payload

	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("## Handoff\nresumen"), protect_last_n=1)
	compactor.compact_now("alma-1")
	payload = rehydrate_payload("alma-1", mirror=mirror)
	assert "## Handoff" in payload
	assert "turno 1" not in payload


def test_purge_removes_dead_soul_compactions(mirror):
	_seed(mirror, 4)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("resumen"), protect_last_n=1)
	compactor.compact_now("alma-1")
	assert mirror.compactions("alma-1")
	mirror.purge(retention_days=0)
	assert mirror.compactions("alma-1") == []


def test_overlapping_range_reuses_existing_compaction(mirror):
	_seed(mirror, 10)
	first = mirror.start_compaction(
		continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=5, compaction_id="c1"
	)
	second = mirror.start_compaction(
		continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=8, compaction_id="c2"
	)
	assert first["compaction_id"] == second["compaction_id"] == "c1"
	assert len(mirror.compactions("alma-1")) == 1


def test_context_does_not_inject_old_compactor_summaries(mirror):
	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("vigente"), protect_last_n=1)
	compactor.compact_now("alma-1")
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="m",
		role="system",
		content="resumen viejo",
		source="compactor",
		source_ref="compact:viejo",
	)
	turns = mirror.context_turns("alma-1")
	assert turns[0]["content"] == "vigente"
	assert all(t["content"] != "resumen viejo" for t in turns)


def test_switch_trims_pin_compaction_summary():
	from red_pill.session.switch import render_history, trim_history_chars, trim_history_window

	turns = [
		{"role": "system", "source": "compactor", "content": "ESTADO CLAVE"},
		*[
			{"role": "user" if i % 2 else "assistant", "content": f"turno {i}"}
			for i in range(1, 31)
		],
	]
	window = trim_history_window(turns, 5)
	assert window[0]["content"] == "ESTADO CLAVE"
	assert len(window) == 6
	chars = trim_history_chars(turns, 60)
	assert chars[0]["content"] == "ESTADO CLAVE"
	rendered = render_history("alma-1", turns, max_chars=80)
	assert "ESTADO CLAVE" in rendered


def test_rehydrate_limit_keeps_summary(mirror):
	from red_pill.session.switch import rehydrate_payload

	_seed(mirror, 30)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("ESTADO CLAVE"), protect_last_n=1)
	compactor.compact_now("alma-1")
	payload = rehydrate_payload("alma-1", mirror=mirror, limit=2)
	assert "ESTADO CLAVE" in payload


def test_mini_session_history_window_keeps_summary(tmp_path):
	from red_pill.mini.session import MiniConfig, MiniSession

	class Provider:
		def __init__(self):
			self.calls = []

		def chat(self, messages, **kwargs):
			self.calls.append(list(messages))
			return {"role": "assistant", "content": "ok"}

	mirror = SessionMirror(str(tmp_path / "session.db"))
	_seed(mirror, 30)
	provider = Provider()
	cfg = MiniConfig(
		workspace=str(tmp_path),
		continuity_id="alma-1",
		mission_id="repo:next",
		db_path=str(tmp_path / "session.db"),
		context_tokens=20,
		history_turns=5,
		compactor_enabled=True,
		compactor_engine="extractive",
		compactor_protect_last_n=1,
	)
	session = MiniSession(cfg, {"forge": provider})
	session.run("forge", system_prompt="You are Forge.", task="continúa", tools=None)
	first = provider.calls[0]
	assert any("Resumen extractivo" in str(m.get("content")) for m in first)
	assert len(first) <= 7  # system + summary + 5 turnos + task


def test_compact_now_uses_existing_overlapping_range(mirror):
	_seed(mirror, 10)
	mirror.start_compaction(
		continuity_id="alma-1", mission_id="repo:next", range_start_seq=1, range_end_seq=5, compaction_id="c1"
	)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("resumen"), protect_last_n=1)
	done = compactor.compact_now("alma-1")
	assert done is not None
	assert done["compaction_id"] == "c1"
	assert done["range_end_seq"] == 5
	assert len(mirror.compactions("alma-1")) == 1
	assert mirror.context_turns("alma-1")[0]["content"] == "resumen"


def test_reset_after_compaction_is_not_a_noop(mirror):
	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("viejo"), protect_last_n=1)
	compactor.compact_now("alma-1")
	done = compactor.reset("alma-1", summary="## Handoff\nnuevo", mission_id="repo:next")
	assert done["status"] == "completed"
	assert done["summary"] == "## Handoff\nnuevo"
	assert compactor.context("alma-1").turns[0]["content"] == "## Handoff\nnuevo"
	statuses = [c["status"] for c in mirror.compactions("alma-1")]
	assert statuses.count("completed") == 1 and statuses.count("aborted") == 1


def test_safe_cut_with_pending_tool_result(mirror):
	_seed(mirror, 6)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:next",
		role="assistant",
		content=None,
		tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
		source_ref="call",
	)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:next",
		role="tool",
		content="pendiente",
		tool_call_id="call_1",
		source_ref="result",
	)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("resumen"), protect_last_n=1)
	done = compactor.compact_now("alma-1")
	assert done["range_end_seq"] == 6
	ctx = mirror.context_turns("alma-1")
	assert ctx[0]["content"] == "resumen"
	assert [t["role"] for t in ctx[1:3]] == ["assistant", "tool"]
	assert ctx[1]["tool_calls"][0]["id"] == "call_1"
	assert ctx[2]["tool_call_id"] == "call_1"


def test_context_includes_parent_summary_before_latest(mirror):
	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("viejo"), protect_last_n=0)
	compactor.compact_now("alma-1")
	for i in (7, 8):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"t{i}")
	compactor.summarizer = FakeSummarizer("nuevo")
	compactor.compact_now("alma-1")
	turns = mirror.context_turns("alma-1")
	assert [t["content"] for t in turns[:2]] == ["viejo", "nuevo"]
	assert [t["content"] for t in turns[2:]] == []


def test_compaction_aborted_by_peer_does_not_raise(mirror):
	class AbortingSummarizer(FakeSummarizer):
		def summarize(self, **kwargs):
			row = mirror.compactions("alma-1")[-1]
			mirror.abort_compaction(row["compaction_id"], reason="peer")
			return "resumen"

	_seed(mirror, 6)
	compactor = Compactor(mirror, summarizer=AbortingSummarizer(), protect_last_n=1)
	ctx = compactor.ensure_context("alma-1", budget_tokens=1, reserve_tokens=0)
	assert ctx.compacted is False
	assert mirror.latest_compaction("alma-1") is None


def test_context_keeps_full_summary_chain(mirror):
	_summaries = ["A", "B", "C"]
	_seed(mirror, 4)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("A"), protect_last_n=0)
	compactor.compact_now("alma-1")
	for i in (5, 6):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"t{i}")
	compactor.summarizer = FakeSummarizer("B")
	compactor.compact_now("alma-1")
	for i in (7, 8):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"t{i}")
	compactor.summarizer = FakeSummarizer("C")
	compactor.compact_now("alma-1")
	turns = mirror.context_turns("alma-1")
	assert [t["content"] for t in turns if t["role"] == "system"] == _summaries


def test_reset_then_compaction_keeps_handoff(mirror):
	_seed(mirror, 4)
	compactor = Compactor(mirror, summarizer=FakeSummarizer("viejo"), protect_last_n=0)
	compactor.compact_now("alma-1")
	compactor.reset("alma-1", summary="HANDOFF", mission_id="repo:next")
	for i in (5, 6, 7):
		mirror.append_turn(continuity_id="alma-1", mission_id="repo:next", role="user", content=f"turno {i}", source_ref=f"r{i}")
	compactor.summarizer = FakeSummarizer("nuevo")
	compactor.compact_now("alma-1")
	turns = mirror.context_turns("alma-1")
	assert "HANDOFF" in [t["content"] for t in turns if t["role"] == "system"]


def test_maybe_start_enqueues_one_durable_script_job(mirror):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	qm = CognitiveQueueManager(str(mirror.db_path + ".queue"))
	_seed(mirror, 8)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), background_tokens=1, queue_manager=qm)
	job_id = compactor.maybe_start("alma-1", mission_id="repo:next", originator="job:test")
	assert job_id
	again = compactor.maybe_start("alma-1", mission_id="repo:next", originator="job:test")
	assert again == job_id
	task = qm.get_task(job_id)
	assert task is not None
	payload = task["payload"]
	assert payload["continuity_id"] == "alma-1"
	assert payload["mission_id"] == "repo:next"
	cmd = payload["step_command"]
	assert "--continuity" in cmd and "alma-1" in cmd
	assert "--mission" in cmd and "repo:next" in cmd
	assert "--db-path" in cmd and payload["control"] == {"max_step_minutes": 15}


def test_is_context_length_error_matches_provider_rejections():
	assert is_context_length_error(RuntimeError("This model's maximum context length is 4096 tokens"))
	assert is_context_length_error(RuntimeError("context_length_exceeded"))
	assert is_context_length_error(RuntimeError("prompt is too long: reduce the length"))
	assert not is_context_length_error(RuntimeError("rate limit exceeded"))


def test_mini_session_retries_after_context_length_rejection(tmp_path):
	from red_pill.mini.session import MiniConfig, MiniSession

	class Provider:
		def __init__(self):
			self.calls = []

		def chat(self, messages, **kwargs):
			self.calls.append([dict(m) for m in messages])
			if len(self.calls) == 1:
				raise RuntimeError("This model's maximum context length is 4096 tokens")
			return {"role": "assistant", "content": "ok"}

	mirror = SessionMirror(str(tmp_path / "session.db"))
	_seed(mirror, 8)
	provider = Provider()
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=1)
	cfg = MiniConfig(
		workspace=str(tmp_path),
		continuity_id="alma-1",
		mission_id="repo:next",
		db_path=str(tmp_path / "session.db"),
		context_tokens=8000,
	)
	session = MiniSession(cfg, {"forge": provider}, compactor=compactor)
	out = session.run("forge", system_prompt="You are Forge.", task="continúa", tools=None)

	assert out["text"] == "ok"
	assert len(provider.calls) == 2
	first = provider.calls[0]
	second = provider.calls[1]
	assert any(str(m.get("content")) == "turno 1" for m in first)
	assert not any(str(m.get("content")) == "turno 1" for m in second)
	assert any("resumen" in str(m.get("content")) for m in second)
	assert mirror.latest_compaction("alma-1") is not None


def test_context_estimate_is_cheap_and_shrinks_after_compaction(mirror):
	_seed(mirror, 8)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), protect_last_n=1)
	before = compactor.estimate_context_tokens("alma-1")
	assert before > 0
	compactor.compact_now("alma-1")
	after = compactor.estimate_context_tokens("alma-1")
	assert after < before


def test_maybe_start_estimate_skips_context_read(mirror, monkeypatch):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	qm = CognitiveQueueManager(str(mirror.db_path + ".queue"))
	_seed(mirror, 8)
	compactor = Compactor(mirror, summarizer=FakeSummarizer(), background_tokens=1, queue_manager=qm)

	def _boom(*args, **kwargs):
		raise AssertionError("context_messages no debe leerse con estimated_tokens")

	monkeypatch.setattr(mirror, "context_messages", _boom)
	job = compactor.maybe_start("alma-1", mission_id="repo:next", estimated_tokens=999, originator="job:test")
	assert job
