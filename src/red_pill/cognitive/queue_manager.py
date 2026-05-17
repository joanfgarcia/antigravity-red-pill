import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CognitiveQueueManager:
	"""
	Gestor soberano de la cola asíncrona.
	Soporta operaciones concurrentes gracias al modo WAL de SQLite.
	Las tareas inyectadas aquí pueden despertar tanto a Minions simples
	como al propio Enjambre Soberano (Aleth) en modo background.
	"""

	def __init__(self, db_path: Optional[str] = None):
		if not db_path:
			# Por defecto vive junto a las memorias del Bünker (ahora en XDG data dir)
			from red_pill.core.paths import get_queue_dir

			db_path = str(get_queue_dir() / "bunker_queue.db")

		self.db_path = db_path
		self._init_db()

	def _get_connection(self) -> sqlite3.Connection:
		conn = sqlite3.connect(self.db_path, timeout=5.0)  # 5s timeout to avoid locked errors
		conn.row_factory = sqlite3.Row
		return conn

	def _init_db(self) -> None:
		with self._get_connection() as conn:
			# Habilitar WAL para concurrencia IDE vs Daemon
			conn.execute("PRAGMA journal_mode=WAL;")
			conn.execute("PRAGMA synchronous=NORMAL;")

			conn.execute("""
				CREATE TABLE IF NOT EXISTS cognitive_tasks (
					id TEXT PRIMARY KEY,
					source TEXT NOT NULL,
					priority INTEGER NOT NULL DEFAULT 5,
					payload TEXT NOT NULL,
					status TEXT NOT NULL DEFAULT 'PENDING',
					created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					attempts INTEGER NOT NULL DEFAULT 0,
					error_log TEXT
				)
			""")

			# Índice para extracción ultrarrápida del router
			conn.execute("""
				CREATE INDEX IF NOT EXISTS idx_queue_routing
				ON cognitive_tasks(status, priority DESC, created_at ASC)
			""")

	def enqueue_task(self, source: str, payload: Dict[str, Any], priority: int = 5) -> str:
		"""Inyecta un estímulo/tarea en la cola cognitiva."""
		task_id = str(uuid.uuid4())
		payload_str = json.dumps(payload)

		with self._get_connection() as conn:
			conn.execute(
				"""
				INSERT INTO cognitive_tasks (id, source, priority, payload, status)
				VALUES (?, ?, ?, ?, 'PENDING')
				""",
				(task_id, source, priority, payload_str),
			)
		logger.debug(f"[QUEUE] Task {task_id} injected (Priority {priority}). Source: {source}")
		return task_id

	def pop_next_task(self) -> Optional[Dict[str, Any]]:
		"""
		Extrae la tarea de mayor prioridad. Marca como PROCESSING atómicamente.
		Retorna la tarea o None si la cola está vacía.
		"""
		with self._get_connection() as conn:
			conn.execute("BEGIN EXCLUSIVE")
			cursor = conn.execute(
				"""
				SELECT id, source, priority, payload, attempts
				FROM cognitive_tasks
				WHERE status = 'PENDING'
				ORDER BY priority DESC, created_at ASC
				LIMIT 1
				"""
			)
			row = cursor.fetchone()

			if not row:
				conn.execute("COMMIT")
				return None

			task_id = row["id"]
			# Marcar atómicamente
			conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP
				WHERE id = ?
				""",
				(task_id,),
			)
			conn.execute("COMMIT")

			return {
				"id": task_id,
				"source": row["source"],
				"priority": row["priority"],
				"attempts": row["attempts"],
				"payload": json.loads(row["payload"]),
			}

	def mark_completed(self, task_id: str) -> None:
		"""Marca una tarea como finalizada exitosamente."""
		with self._get_connection() as conn:
			conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
				WHERE id = ?
				""",
				(task_id,),
			)

	def mark_failed(self, task_id: str, error_msg: str) -> None:
		"""
		Marca un fallo. Incrementa intentos.
		Si attempts > 3, activa el disyuntor y la etiqueta como FRUSTRATED.
		"""
		with self._get_connection() as conn:
			# Primero incrementamos intentos
			conn.execute(
				"""
				UPDATE cognitive_tasks
				SET attempts = attempts + 1,
					error_log = ?,
					updated_at = CURRENT_TIMESTAMP
				WHERE id = ?
				""",
				(error_msg, task_id),
			)

			# Comprobamos el disyuntor de frustración
			cursor = conn.execute("SELECT attempts FROM cognitive_tasks WHERE id = ?", (task_id,))
			row = cursor.fetchone()

			if row and row["attempts"] >= 3:
				conn.execute("UPDATE cognitive_tasks SET status = 'FRUSTRATED' WHERE id = ?", (task_id,))
				logger.error(f"[QUEUE] Task {task_id} marked as FRUSTRATED (Circuit Breaker Activated).")
			else:
				conn.execute("UPDATE cognitive_tasks SET status = 'PENDING' WHERE id = ?", (task_id,))
				logger.warning(f"[QUEUE] Task {task_id} failed. Returned to PENDING queue.")
