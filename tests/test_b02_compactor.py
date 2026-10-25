"""B-02 — esquema de compactaciones, contexto podado y puerto de resumen."""

from __future__ import annotations

import sqlite3

import pytest

from red_pill.core import prompts as core
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.session.summarizer import (
	ExtractiveSummarizer,
	FallbackSummarizer,
	MementoSummarizer,
	SamanthaSummarizer,
	SummaryUnavailable,
	build_summarizer,
	render_compaction_prompt,
)


@pytest.fixture
def mirror(tmp_path):
	return SessionMirror(str(tmp_path / "session.db"))


def _seed(mirror: SessionMirror, n: int = 5) -> None:
	for i in range(1, n + 1):
		mirror.append_turn(
			continuity_id="alma-1",
			mission_id="repo:next",
			role="assistant" if i % 2 else "user",
			content=f"turno {i}",
			source_ref=f"t{i}",
			ts=float(i),
		)


class TestCompactionSchema:
	def test_schema_has_session_compactions_v7(self, tmp_path):
		path = tmp_path / "session.db"
		SessionRegistry(str(path))
		con = sqlite3.connect(path)
		assert con.execute("PRAGMA user_version").fetchone()[0] == 7
		cols = {row[1] for row in con.execute("PRAGMA table_info(session_compactions)").fetchall()}
		assert {"compaction_id", "continuity_id", "range_start_seq", "range_end_seq", "summary", "parent_compaction_id"} <= cols
		con.close()

	def test_implements_compaction_contract(self, mirror):
		from red_pill.session.contracts import CompactionStore

		assert isinstance(mirror, CompactionStore)

	def test_compactor_flags_are_off_by_default(self):
		import red_pill.config as cfg

		c = cfg.get_config()
		assert c.SESSION_COMPACTOR_ENABLED is False
		assert c.SESSION_COMPACTOR_ENGINE == "samantha"
		assert c.SESSION_COMPACTOR_PROTECT_LAST_N == 4

	def test_roundtrip_complete_and_context(self, mirror):
		_seed(mirror, 5)
		pending = mirror.start_compaction(
			continuity_id="alma-1",
			mission_id="repo:next",
			range_start_seq=1,
			range_end_seq=3,
			compaction_id="c1",
			tokens_before=1000,
		)
		assert pending["status"] == "pending"
		done = mirror.complete_compaction("c1", summary="## Estado\nhecho 1-3", model="samantha", tokens_after=120)
		assert done["status"] == "completed" and done["summary"].startswith("## Estado")
		assert mirror.latest_compaction("alma-1")["compaction_id"] == "c1"
		turns = mirror.context_turns("alma-1")
		assert [t["content"] for t in turns] == ["## Estado\nhecho 1-3", "turno 4", "turno 5"]
		assert turns[0]["role"] == "system" and turns[0]["source"] == "compactor"
		# El histórico completo sigue intacto: 5 turnos + el resumen.
		assert mirror.count_turns("alma-1") == 6

	def test_complete_is_idempotent(self, mirror):
		_seed(mirror, 3)
		mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=2, compaction_id="c1")
		mirror.complete_compaction("c1", summary="resumen")
		mirror.complete_compaction("c1", summary="otro")
		assert mirror.count_turns("alma-1") == 4
		assert len([c for c in mirror.compactions("alma-1") if c["status"] == "completed"]) == 1

	def test_protect_last_n_keeps_recent_turns(self, mirror):
		_seed(mirror, 8)
		mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=6, compaction_id="c1")
		mirror.complete_compaction("c1", summary="resumen")
		turns = mirror.context_turns("alma-1")
		assert [t["content"] for t in turns] == ["resumen", "turno 7", "turno 8"]

	def test_aborted_compaction_does_not_change_context(self, mirror):
		_seed(mirror, 3)
		mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=2, compaction_id="c1")
		mirror.abort_compaction("c1", reason="timeout")
		assert mirror.latest_compaction("alma-1") is None
		assert [t["content"] for t in mirror.context_turns("alma-1")] == ["turno 1", "turno 2", "turno 3"]

	def test_parent_compaction_is_preserved(self, mirror):
		_seed(mirror, 4)
		mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=2, compaction_id="c1")
		mirror.complete_compaction("c1", summary="uno")
		mirror.start_compaction(
			continuity_id="alma-1",
			mission_id="m",
			range_start_seq=3,
			range_end_seq=4,
			compaction_id="c2",
			parent_compaction_id="c1",
		)
		mirror.complete_compaction("c2", summary="dos")
		assert mirror.latest_compaction("alma-1")["parent_compaction_id"] == "c1"

	def test_context_messages_preserve_tool_pair(self, mirror):
		_seed(mirror, 2)
		mirror.append_turn(
			continuity_id="alma-1",
			mission_id="m",
			role="assistant",
			content=None,
			tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
		)
		mirror.append_turn(continuity_id="alma-1", mission_id="m", role="tool", content="ok", tool_call_id="call_1")
		mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=1, range_end_seq=2, compaction_id="c1")
		mirror.complete_compaction("c1", summary="resumen")
		messages = mirror.context_messages("alma-1")
		assert [m["role"] for m in messages] == ["system", "assistant", "tool"]
		assert messages[1]["tool_calls"][0]["id"] == "call_1"
		assert messages[2]["tool_call_id"] == "call_1"

	def test_invalid_ranges_rejected(self, mirror):
		with pytest.raises(ValueError):
			mirror.start_compaction(continuity_id="alma-1", mission_id="m", range_start_seq=3, range_end_seq=2)
		with pytest.raises(ValueError):
			mirror.start_compaction(continuity_id="", mission_id="m", range_start_seq=1, range_end_seq=2)


class TestSummarizers:
	def test_prompt_has_operational_sections(self):
		text = render_compaction_prompt("user: hola\nassistant: mundo", "prioriza tests")
		assert "<historial>" in text and "prioriza tests" in text
		assert "## Decisiones" in text and "## Siguiente paso" in text
		assert core.validate_all() == []

	def test_samantha_summarizer_passes_prompt_and_returns_text(self):
		calls = {}

		def fake_invoke(**kwargs):
			calls.update(kwargs)
			return "## Estado\nok"

		out = SamanthaSummarizer(fake_invoke).summarize(text="historial", instructions="sé breve", max_tokens=123)
		assert out == "## Estado\nok"
		assert calls["max_tokens"] == 123
		assert "<historial>" in calls["prompt"] and "sé breve" in calls["prompt"]
		assert calls["system_prompt"]

	def test_samantha_empty_is_unavailable(self):
		with pytest.raises(SummaryUnavailable):
			SamanthaSummarizer(lambda **_: "").summarize(text="x")

	def test_memento_uses_local_transport(self):
		seen = {}

		def fake_transport(system, user, max_tokens):
			seen.update(system=system, user=user, max_tokens=max_tokens)
			return "## Estado\nmemento"

		out = MementoSummarizer(fake_transport).summarize(text="historial", max_tokens=200)
		assert out == "## Estado\nmemento"
		assert "compactador" in seen["system"].lower()
		assert "<historial>" in seen["user"] and seen["max_tokens"] == 200

	def test_fallback_uses_extractive_when_primary_fails(self):
		class Broken:
			name = "broken"

			def summarize(self, **kwargs):
				raise RuntimeError("no model")

		out = FallbackSummarizer(Broken()).summarize(
			text="decisión: usar Samantha\npendiente: tests\nsiguiente: commit",
			max_tokens=80,
		)
		assert "Resumen extractivo" in out
		assert "pendiente: tests" in out

	def test_extractive_never_empty(self):
		out = ExtractiveSummarizer().summarize(text="uno\ndos\ntres")
		assert "uno" in out and "tres" in out

	def test_build_summarizer(self):
		assert build_summarizer("extractive").name == "extractive"
		assert build_summarizer("samantha").name == "samantha+fallback"
		assert build_summarizer("memento").name == "memento+fallback"
		with pytest.raises(ValueError):
			build_summarizer("nope")
