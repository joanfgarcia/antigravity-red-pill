"""Tests de Fase 2 — heavy path (RFC_TELEGRAM_RESILIENCE D13/D16-D19/D22).

Covers:
  - queue_manager: list_tasks(mission_prefix=...) filtra por prefijo (D22)
  - queue_manager: set_checkpoint_key preserva el resto del checkpoint (D19)
  - _enqueue_heavy_path: enqueue agentic_job con cascade + ack "⏳ en cola" +
    mission_id telegram: + payload.telegram_channel_user_id (D16/D18)
  - _check_telegram_jobs: entrega COMPLETED/FRUSTRATED al outbox, dedup con
    set_checkpoint_key (D19)
"""

import json
import sqlite3
from unittest.mock import patch

import pytest

import red_pill.plugins.antigravity_ide.worker as worker_module
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.plugins.antigravity_ide.worker import IDEWorker


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
	db_path = tmp_path / "events.db"
	conn = sqlite3.connect(str(db_path))
	for table in (
		"""
		CREATE TABLE IF NOT EXISTS inbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel TEXT NOT NULL,
			channel_user_id TEXT NOT NULL,
			payload TEXT NOT NULL,
			status TEXT DEFAULT 'PENDING',
			retries INTEGER DEFAULT 0
		)""",
		"""
		CREATE TABLE IF NOT EXISTS outbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel TEXT,
			channel_user_id TEXT,
			cascade_id TEXT,
			payload TEXT
		)""",
		"""
		CREATE TABLE IF NOT EXISTS telegram_sessions (
			channel_user_id TEXT PRIMARY KEY,
			cascade_id TEXT,
			cascade_type TEXT,
			model TEXT,
			backend TEXT
		)""",
	):
		conn.execute(table)
	conn.commit()
	conn.close()
	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	return db_path


@pytest.fixture
def queue_manager(tmp_path):
	"""CognitiveQueueManager aislado en bunker_queue.db de tmp_path."""
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


class TestQueueManagerD22:
	def test_list_tasks_mission_prefix(self, queue_manager):
		queue_manager.enqueue_task("agentic_job", {"prompt": "a"}, mission_id="telegram:user_a")
		queue_manager.enqueue_task("agentic_job", {"prompt": "b"}, mission_id="other:user_a")

		by_prefix = queue_manager.list_tasks(statuses=["PENDING"], mission_prefix="telegram:")
		assert len(by_prefix) == 1
		assert by_prefix[0]["mission_id"] == "telegram:user_a"

	def test_set_checkpoint_key_preserves_rest(self, queue_manager):
		task_id = queue_manager.enqueue_task("agentic_job", {"prompt": "x"}, mission_id="telegram:u")
		queue_manager.save_checkpoint(task_id, {"response": "hola"})
		queue_manager.set_checkpoint_key(task_id, "telegram_delivered", True)

		task = queue_manager.get_task(task_id)
		assert task["checkpoint_data"]["response"] == "hola"
		assert task["checkpoint_data"]["telegram_delivered"] is True


class TestEnqueueHeavyPath:
	def test_enqueues_agentic_job_with_ack(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as mock_qm:
			mock_qm.return_value.enqueue_task.return_value = "job-789"
			worker._enqueue_heavy_path(
				text="implementa el modulo",
				channel="telegram",
				channel_user_id="user_a",
				msg_ids=[1],
				cursor=cursor,
				conn=conn,
			)

		kwargs = mock_qm.return_value.enqueue_task.call_args[1]
		assert kwargs["source"] == "agentic_job"
		payload = kwargs["payload"]
		assert payload["prompt"] == "implementa el modulo"
		assert payload["telegram_channel_user_id"] == "user_a"
		assert kwargs["mission_id"] == "telegram:user_a"
		assert "cascade" in payload  # D16: siempre cascade

		# ack en outbox
		conn.close()
		conn2 = sqlite3.connect(str(mock_db))
		row = conn2.execute("SELECT payload FROM outbox LIMIT 1").fetchone()
		assert "En cola" in json.loads(row[0])["text"]
		conn2.close()

	def test_uses_session_override_model(self, mock_db, tmp_path):
		"""D9/D20: override de sesión → el router (catálogo aislado) antepone el modelo."""
		from red_pill.core.model_catalog import ModelCatalog
		from red_pill.core.model_router import CascadeRouter

		# Catálogo aislado (CI no tiene ~/.config/red-pill/model_catalog.yaml)
		catalog_yaml = tmp_path / "model_catalog.yaml"
		catalog_yaml.write_text(
			"""
catalog:
  providers:
    opencode:
      models:
        - id: "opencode-go/deepseek-v4-pro"
          backend: "opencode"
          tier: "subscription"
          priority: 1
          roles: ["conversational"]
          not_capable_for: []
roles:
  conversational:
    - "opencode-go/deepseek-v4-pro"
""",
			encoding="utf-8",
		)
		router = CascadeRouter(catalog=ModelCatalog(path=catalog_yaml))

		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		# Sesión con override de modelo
		cursor.execute(
			"INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type, model, backend) "
			"VALUES ('user_a', 'sess1', 'local_session', 'opencode-go/deepseek-v4-pro', 'opencode')"
		)
		conn.commit()

		with patch("red_pill.core.model_router.get_router", return_value=router):
			with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as mock_qm:
				mock_qm.return_value.enqueue_task.return_value = "job-abc"
				worker._enqueue_heavy_path(
					text="tarea", channel="telegram", channel_user_id="user_a", msg_ids=[1], cursor=cursor, conn=conn
				)

		payload = mock_qm.return_value.enqueue_task.call_args[1]["payload"]
		assert payload["cascade"][0]["model"] == "opencode-go/deepseek-v4-pro"
		conn.close()


class TestCheckTelegramJobs:
	def _seed_job(self, queue_manager, status="COMPLETED", response="resultado final", user="user_a"):
		task_id = queue_manager.enqueue_task(
			"agentic_job",
			{"prompt": "p", "telegram_channel_user_id": user, "telegram_chat_id": "telegram"},
			mission_id=f"telegram:{user}",
		)
		queue_manager.save_checkpoint(task_id, {"response": response})
		with queue_manager._get_connection() as conn:
			conn.execute("UPDATE cognitive_tasks SET status = ? WHERE id = ?", (status, task_id))
		return task_id

	def test_delivers_completed(self, mock_db, queue_manager):
		worker = IDEWorker.__new__(IDEWorker)
		self._seed_job(queue_manager, status="COMPLETED", response="el resultado")

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=queue_manager):
			worker._check_telegram_jobs()

		conn = sqlite3.connect(str(mock_db))
		row = conn.execute("SELECT payload FROM outbox LIMIT 1").fetchone()
		assert row is not None
		assert "el resultado" in json.loads(row[0])["text"]
		conn.close()

	def test_delivers_frustrated_error(self, mock_db, queue_manager):
		worker = IDEWorker.__new__(IDEWorker)
		self._seed_job(queue_manager, status="FRUSTRATED", response="")

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=queue_manager):
			worker._check_telegram_jobs()

		conn = sqlite3.connect(str(mock_db))
		row = conn.execute("SELECT payload FROM outbox LIMIT 1").fetchone()
		assert row is not None
		assert "falló" in json.loads(row[0])["text"]
		conn.close()

	def test_dedup_no_double_delivery(self, mock_db, queue_manager):
		worker = IDEWorker.__new__(IDEWorker)
		task_id = self._seed_job(queue_manager, status="COMPLETED", response="r1")

		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=queue_manager):
			worker._check_telegram_jobs()
			worker._check_telegram_jobs()  # segundo pulse

		task = queue_manager.get_task(task_id)
		assert task["checkpoint_data"].get("telegram_delivered") is True

		conn = sqlite3.connect(str(mock_db))
		count = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
		assert count == 1
		conn.close()
