"""Fase 1a — espejo canónico de turnos (`session_mirror`, schema v4).

Cubre: roundtrip con `tool_calls` intactos, secuencia por alma, idempotencia del
backfill por `source_ref`, migración v3→v4 y extracción canónica desde los
transcripts de opencode/claude_code (pareja tool-call ↔ resultado).
"""

import json
import sqlite3

import pytest

from red_pill.chronicle_sources.claude_code import ClaudeCodeSourcePlugin
from red_pill.chronicle_sources.opencode import OpencodeSourcePlugin
from red_pill.session.mirror import SessionMirror, SessionSourceNotFound, sync_originator, sync_registry
from red_pill.session.store import SessionRegistry


@pytest.fixture
def mirror(tmp_path):
	return SessionMirror(str(tmp_path / "session.db"))


@pytest.fixture
def registry(tmp_path):
	return SessionRegistry(str(tmp_path / "session.db"))


class TestMirrorStore:
	def test_roundtrip_preserves_tool_calls(self, mirror):
		calls = [
			{
				"id": "call_1",
				"type": "function",
				"function": {"name": "bash", "arguments": '{"command":"ls"}'},
			}
		]
		turn = mirror.append_turn(
			continuity_id="alma-1",
			mission_id="repo:main",
			role="assistant",
			content=None,
			tool_calls=calls,
			model="gpt-x",
			ts=1.5,
			global_turn=7,
			originator="opencode:s1",
			source="opencode",
			source_ref="m1",
		)
		assert turn is not None and turn["seq"] == 1
		mirror.append_turn(
			continuity_id="alma-1",
			mission_id="repo:main",
			role="tool",
			content="file-a\nfile-b",
			tool_call_id="call_1",
			ts=1.6,
			originator="opencode:s1",
			source="opencode",
			source_ref="m2",
		)
		turns = mirror.read_turns("alma-1")
		assert [t["role"] for t in turns] == ["assistant", "tool"]
		assert turns[0]["tool_calls"] == calls
		assert turns[1]["tool_call_id"] == "call_1"
		assert turns[1]["content"] == "file-a\nfile-b"
		assert turns[0]["model"] == "gpt-x"
		assert turns[0]["global_turn"] == 7

	def test_seq_is_per_soul(self, mirror):
		first = mirror.append_turn(continuity_id="alma-1", mission_id="m", role="user", content="a")
		second = mirror.append_turn(continuity_id="alma-2", mission_id="m", role="user", content="b")
		third = mirror.append_turn(continuity_id="alma-1", mission_id="m", role="user", content="c")
		assert (first["seq"], second["seq"], third["seq"]) == (1, 1, 2)
		assert mirror.count_turns("alma-1") == 2
		assert mirror.last_seq("alma-1") == 2
		assert [t["content"] for t in mirror.read_turns("alma-1", since_seq=1)] == ["c"]

	def test_invalid_turn_rejected(self, mirror):
		with pytest.raises(ValueError):
			mirror.append_turn(continuity_id="", mission_id="m", role="user", content="x")
		with pytest.raises(ValueError):
			mirror.append_turn(continuity_id="a", mission_id="", role="user", content="x")
		with pytest.raises(ValueError):
			mirror.append_turn(continuity_id="a", mission_id="m", role="nope", content="x")
		with pytest.raises(ValueError):
			mirror.append_turn(continuity_id="a", mission_id="m", role="assistant", tool_calls={"not": "a list"})

	def test_source_ref_makes_backfill_idempotent(self, mirror):
		args = dict(
			continuity_id="alma-1",
			mission_id="m",
			role="user",
			content="hola",
			originator="claude_code:s1",
			source="claude_code",
			source_ref="uuid-1",
		)
		assert mirror.append_turn(**args) is not None
		assert mirror.append_turn(**args) is None
		assert mirror.count_turns("alma-1") == 1

	def test_append_turns_bulk_dedupes(self, mirror):
		turns = [
			{"role": "user", "content": "a", "ts": 1.0, "source_ref": "1"},
			{"role": "assistant", "content": "b", "ts": 2.0, "source_ref": "2"},
		]
		assert mirror.append_turns("alma-1", turns, mission_id="m", originator="opencode:s1", source="opencode") == 2
		assert mirror.append_turns("alma-1", turns, mission_id="m", originator="opencode:s1", source="opencode") == 0
		assert mirror.last_seq("alma-1") == 2
		turns.append({"role": "user", "content": "c", "ts": 3.0, "source_ref": "3"})
		assert mirror.append_turns("alma-1", turns, mission_id="m", originator="opencode:s1", source="opencode") == 1
		assert mirror.last_seq("alma-1") == 3

	def test_implements_contract(self, mirror):
		from red_pill.session.contracts import MirrorStore

		assert isinstance(mirror, MirrorStore)

	def test_schema_is_v4(self, tmp_path):
		path = tmp_path / "session.db"
		SessionRegistry(str(path))
		con = sqlite3.connect(path)
		assert con.execute("PRAGMA user_version").fetchone()[0] == 4
		assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_mirror'").fetchone()
		con.close()

	def test_migration_v3_recreates_mirror_table(self, tmp_path):
		path = tmp_path / "session.db"
		SessionRegistry(str(path))
		con = sqlite3.connect(path)
		con.execute("DROP TABLE session_mirror")
		con.execute("PRAGMA user_version=3")
		con.commit()
		con.close()
		SessionRegistry(str(path))
		con = sqlite3.connect(path)
		assert con.execute("PRAGMA user_version").fetchone()[0] == 4
		assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_mirror'").fetchone()
		con.close()


class TestCanonicalExtraction:
	def test_opencode_preserves_tool_pair(self):
		msg_rows = [
			(
				"m1",
				json.dumps(
					{
						"role": "assistant",
						"modelID": "gpt-x",
						"time": {"created": 1700000000000},
					}
				),
				1700000000000,
			)
		]
		part_rows = [
			("m1", json.dumps({"type": "text", "text": "voy a mirar"})),
			(
				"m1",
				json.dumps(
					{
						"type": "tool",
						"tool": "bash",
						"callID": "call_1",
						"state": {"input": {"command": "ls"}, "output": "a.txt"},
					}
				),
			),
		]
		turns = OpencodeSourcePlugin(db_path="/nonexistent/opencode.db")._normalize_rows_canonical(msg_rows, part_rows)
		assert [t["role"] for t in turns] == ["assistant", "tool"]
		assert turns[0]["content"] == "voy a mirar"
		assert turns[0]["tool_calls"][0]["id"] == "call_1"
		assert turns[0]["tool_calls"][0]["function"]["name"] == "bash"
		assert json.loads(turns[0]["tool_calls"][0]["function"]["arguments"]) == {"command": "ls"}
		assert turns[1]["tool_call_id"] == "call_1"
		assert turns[1]["content"] == "a.txt"
		assert turns[0]["ts"] == 1700000000.0

	def test_claude_preserves_tool_call_and_result(self, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		path = proj / "s1.jsonl"
		records = [
			{"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "mira"}},
			{
				"type": "assistant",
				"uuid": "a1",
				"timestamp": "2026-01-01T00:00:01Z",
				"message": {
					"role": "assistant",
					"model": "claude-x",
					"content": [
						{"type": "text", "text": "voy"},
						{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
					],
				},
			},
			{
				"type": "user",
				"uuid": "u2",
				"timestamp": "2026-01-01T00:00:02Z",
				"message": {
					"role": "user",
					"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.txt"}],
				},
			},
		]
		path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
		plugin = ClaudeCodeSourcePlugin(base_dir=tmp_path)
		turns = plugin.load_canonical("s1")
		assert [t["role"] for t in turns] == ["user", "assistant", "tool"]
		assert turns[1]["tool_calls"][0]["id"] == "toolu_1"
		assert turns[1]["model"] == "claude-x"
		assert turns[2]["tool_call_id"] == "toolu_1"
		assert turns[2]["content"] == "a.txt"

	def test_sync_originator_backfills_and_dedupes(self, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		records = [
			{"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "hola"}},
			{"type": "assistant", "uuid": "a1", "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hey"}]}},
		]
		(proj / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
		mirror = SessionMirror(str(tmp_path / "session.db"))
		reg = SessionRegistry(str(tmp_path / "session.db"))
		reg.upsert_session(originator="claude_code:s1", continuity_id="alma-1", mission_id="repo:main")
		report = sync_registry(mirror, reg, originator="claude_code:s1", base_dirs={"claude_code": str(tmp_path)})
		assert report == [{"originator": "claude_code:s1", "provider": "claude_code", "inserted": 2, "error": None}]
		again = sync_registry(mirror, reg, originator="claude_code:s1", base_dirs={"claude_code": str(tmp_path)})
		assert again[0]["inserted"] == 0
		assert mirror.count_turns("alma-1") == 2

	def test_sync_without_source_is_explicit_not_silent(self, mirror):
		with pytest.raises(SessionSourceNotFound):
			sync_originator(mirror, originator="mystery:s1", continuity_id="alma-1", mission_id="m")


class TestRetentionAndStats:
	def _turn(self, mirror, continuity, *, ts, originator="opencode:s1", mission="m"):
		return mirror.append_turn(
			continuity_id=continuity,
			mission_id=mission,
			role="user",
			content="x",
			ts=ts,
			originator=originator,
			source="opencode",
			source_ref=f"{continuity}:{ts}",
		)

	def test_stats_counts_souls_and_bytes(self, tmp_path):
		import time

		db = str(tmp_path / "session.db")
		mirror = SessionMirror(db)
		reg = SessionRegistry(db)
		reg.upsert_session(originator="opencode:live", continuity_id="alive", mission_id="m")
		reg.upsert_session(originator="opencode:dead", continuity_id="dead", mission_id="m")
		reg.unregister_session("opencode:dead")
		self._turn(mirror, "alive", ts=time.time())
		self._turn(mirror, "dead", ts=time.time())
		self._turn(mirror, "orphan", ts=time.time(), originator="opencode:none")
		stats = mirror.stats(retention_days=30)
		assert stats["rows"] == 3
		assert stats["souls"] == 3
		assert stats["active_souls"] == 1
		assert stats["dead_souls"] == 1
		assert stats["orphan_souls"] == 1
		assert stats["db_bytes"] + stats["wal_bytes"] > 0
		assert stats["retention_days"] == 30

	def test_purge_keeps_alive_souls_and_recent_dead(self, tmp_path):
		import time

		db = str(tmp_path / "session.db")
		mirror = SessionMirror(db)
		reg = SessionRegistry(db)
		old = time.time() - 90 * 86400
		reg.upsert_session(originator="opencode:live", continuity_id="alive", mission_id="m")
		reg.upsert_session(originator="opencode:dead", continuity_id="dead_old", mission_id="m")
		reg.upsert_session(originator="opencode:dead2", continuity_id="dead_new", mission_id="m")
		reg.unregister_session("opencode:dead")
		reg.unregister_session("opencode:dead2")
		self._turn(mirror, "alive", ts=old)
		self._turn(mirror, "dead_old", ts=old)
		self._turn(mirror, "dead_new", ts=time.time())
		self._turn(mirror, "orphan_old", ts=old, originator="opencode:none")
		purged = mirror.purge(retention_days=30)
		assert purged["souls_purged"] == 2
		assert purged["rows_purged"] == 2
		assert mirror.count_turns("alive") == 1
		assert mirror.count_turns("dead_new") == 1
		assert mirror.count_turns("dead_old") == 0
		assert mirror.count_turns("orphan_old") == 0

	def test_purge_does_not_guess_unknown_age(self, tmp_path):
		db = str(tmp_path / "session.db")
		mirror = SessionMirror(db)
		reg = SessionRegistry(db)
		reg.upsert_session(originator="opencode:dead", continuity_id="dead", mission_id="m")
		reg.unregister_session("opencode:dead")
		mirror.append_turn(continuity_id="dead", mission_id="m", role="user", content="x", ts=0.0, originator="opencode:dead")
		assert mirror.purge(retention_days=30)["rows_purged"] == 0
		assert mirror.stats(retention_days=30)["unknown_age_souls"] == 1
		assert mirror.count_turns("dead") == 1
