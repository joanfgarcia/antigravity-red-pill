"""
Tests for ítem 5 — keyword detection + [ESCALATE] detector (D2/D10/D11/D14),
RFC_TELEGRAM_RESILIENCE, slice mínimo Fase 1 (signal-only, fast path).

Covers:
  - _detect_routing_keyword: start-of-message, case-insensitive, first token;
    None for non-keywords or keywords mid-message
  - _detect_escalate_marker: tolerant parse within the 64-char window
  - _process_via_bridge strips the keyword from the PROMPT (D10) but keeps the
    original text in session history (D11)
  - the full response is delivered even when [ESCALATE] is detected (Fase 1)
"""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import red_pill.plugins.antigravity_ide.worker as worker_module
from red_pill.plugins.antigravity_ide.worker import IDEWorker, _detect_escalate_marker, _detect_routing_keyword


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
	db_path = tmp_path / "events.db"
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS inbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			message_id TEXT UNIQUE,
			channel TEXT NOT NULL,
			channel_user_id TEXT NOT NULL,
			cascade_id TEXT,
			payload TEXT NOT NULL,
			status TEXT DEFAULT 'PENDING',
			retries INTEGER DEFAULT 0,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS outbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel TEXT,
			channel_user_id TEXT,
			cascade_id TEXT,
			payload TEXT
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS telegram_sessions (
			channel_user_id TEXT PRIMARY KEY,
			cascade_id TEXT,
			cascade_type TEXT,
model TEXT,
			backend TEXT,
			accumulated_len INTEGER
		)
		"""
	)
	conn.commit()
	conn.close()
	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	return db_path


class TestDetectRoutingKeyword:
	def test_mission_inline(self):
		assert _detect_routing_keyword("#mission implementa X") == "#mission"

	def test_mission_command(self):
		assert _detect_routing_keyword("/mission implementa X") == "/mission"

	def test_heavy_and_job(self):
		assert _detect_routing_keyword("#heavy analiza") == "#heavy"
		assert _detect_routing_keyword("#job compila") == "#job"

	def test_case_insensitive(self):
		assert _detect_routing_keyword("#MISSION X") == "#mission"

	def test_none_for_normal_message(self):
		assert _detect_routing_keyword("hola, que tal") is None

	def test_none_for_keyword_mid_message(self):
		assert _detect_routing_keyword("oye #mission esto") is None


class TestDetectEscalateMarker:
	def test_marker_at_start(self):
		assert _detect_escalate_marker("[ESCALATE] voy a implementar") is True

	def test_marker_within_window(self):
		# Tolerant: prefix whitespace/noise before the marker, within 64 chars.
		assert _detect_escalate_marker("  [ESCALATE] tarea larga") is True

	def test_marker_past_window_not_detected(self):
		long_prefix = "x" * 70
		assert _detect_escalate_marker(f"{long_prefix}[ESCALATE]") is False

	def test_no_marker(self):
		assert _detect_escalate_marker("respuesta normal del modelo") is False

	def test_empty(self):
		assert _detect_escalate_marker("") is False


class TestProcessViaBridgeRouting:
	def _make_worker(self, response_text="respuesta"):
		from red_pill.swarm.bridges import ConversationResult

		worker = IDEWorker.__new__(IDEWorker)
		bridge = MagicMock()
		bridge.prompt.return_value = ConversationResult(
			conversation_id="conv", response=response_text, model="opencode-go/deepseek-v4-pro"
		)
		worker._bridge_telegram = bridge
		worker._caps = MagicMock()
		worker._caps.backend.value = "opencode"
		worker._scribe_relay = MagicMock()
		return worker, bridge

	def test_keyword_stripped_from_prompt_but_kept_in_history(self, mock_db):
		"""Fase 2: keyword dispara el heavy path (enqueue) — el prompt encolado
		NO lleva el keyword (D10) y el historial conserva el original (D11)."""
		worker, bridge = self._make_worker()
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as mock_qm:
			mock_qm.return_value.enqueue_task.return_value = "job-123"
			worker._process_via_bridge(
				combined_text="#mission implementa el modulo X",
				msg_ids=[1],
				channel="telegram",
				channel_user_id="user_a",
				cursor=cursor,
				conn=conn,
			)

		# El bridge NO se invoca (heavy path); se encola.
		bridge.prompt.assert_not_called()
		enqueued = mock_qm.return_value.enqueue_task.call_args[1]["payload"]
		assert "#mission" not in enqueued["prompt"]
		assert "implementa el modulo X" in enqueued["prompt"]

		# El historial conserva la versión ORIGINAL (con keyword, D11).
		from red_pill.plugins.antigravity_ide.telegram_session import TelegramSessionManager

		conn.close()
		conn2 = sqlite3.connect(str(mock_db))
		conn2.row_factory = sqlite3.Row
		tsm = TelegramSessionManager()
		row = conn2.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = 'user_a'").fetchone()
		session = tsm.get_session(row["cascade_id"])
		user_steps = [s for s in session["steps"] if s.get("intent") == "USER"]
		assert user_steps and user_steps[-1]["message"]["text"] == "#mission implementa el modulo X"
		conn2.close()

	def test_normal_message_no_strip(self, mock_db):
		worker, bridge = self._make_worker()
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		worker._process_via_bridge(
			combined_text="hola que tal",
			msg_ids=[1],
			channel="telegram",
			channel_user_id="user_a",
			cursor=cursor,
			conn=conn,
		)

		prompt_arg = bridge.prompt.call_args[0][0]
		assert "hola que tal" in prompt_arg
		conn.close()

	def test_escalate_marker_triggers_heavy_path(self, mock_db):
		"""Fase 2: [ESCALATE] detectado → la tarea se ENCOLA (no se entrega la
		respuesta del fast path)."""
		worker, bridge = self._make_worker(response_text="[ESCALATE] implemento el módulo en background")
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as mock_qm:
			mock_qm.return_value.enqueue_task.return_value = "job-456"
			worker._process_via_bridge(
				combined_text="haz una tarea larga",
				msg_ids=[1],
				channel="telegram",
				channel_user_id="user_a",
				cursor=cursor,
				conn=conn,
			)

		# Se encola la petición ORIGINAL (no la respuesta del fast path).
		enqueued = mock_qm.return_value.enqueue_task.call_args[1]["payload"]
		assert "haz una tarea larga" in enqueued["prompt"]
		# El ack "⏳ en cola" va al outbox; la respuesta con marker NO se entrega.
		conn.close()
		conn2 = sqlite3.connect(str(mock_db))
		outbox = conn2.execute("SELECT payload FROM outbox").fetchall()
		outbox_texts = [json.loads(r[0])["text"] for r in outbox]
		assert any("En cola" in t for t in outbox_texts)
		assert not any("[ESCALATE]" in t for t in outbox_texts)
		conn2.close()


class TestD5LocalGuard:
	def test_local_filtered_from_telegram_cascade(self, monkeypatch):
		"""D5: with LOCAL_ALLOWED_FOR_HEAVY=False (default), local targets are
		filtered out of the Telegram bridge cascade built by IDEWorker.__init__."""
		from red_pill.config import BridgeTarget, RedPillConfig

		cascade = [
			BridgeTarget(backend="opencode", model="pro"),
			BridgeTarget(backend="local", model="granite"),
		]
		cfg_inst = RedPillConfig(_env_file=None)
		cfg_inst.TELEGRAM_BRIDGE_CASCADE = cascade
		cfg_inst.LOCAL_ALLOWED_FOR_HEAVY = False
		cfg_inst.AWAKENING_BRIDGE_CASCADE = []
		cfg_inst.DEFAULT_MINION_BRIDGE_CASCADE = []
		monkeypatch.setattr(worker_module.cfg, "get_config", lambda: cfg_inst)

		built = {}
		from red_pill.swarm.bridges.base import AgentBridge

		class _FakeBridge(AgentBridge):
			def __init__(self, *a, **kw):
				pass

			def get_capabilities(self):
				from red_pill.swarm.bridges import BackendType, BridgeCapabilities

				return BridgeCapabilities(backend=BackendType.OPENCODE)

		def _fake_create(cascade, name=None, origin=None):
			built["cascade"] = cascade
			built["name"] = name
			return _FakeBridge()

		with patch("red_pill.plugins.antigravity_ide.worker.create_cascade_bridge", side_effect=_fake_create):
			with patch("red_pill.plugins.antigravity_ide.worker.AntigravityIDEClient"):
				with patch("red_pill.inference.samantha_worker.SamanthaWorker") as mock_sam:
					mock_sam.return_value.start = MagicMock()
					worker = IDEWorker()

		assert all(t.backend != "local" for t in built["cascade"])
		assert len(built["cascade"]) == 1
		assert worker._bridge_telegram is not None
