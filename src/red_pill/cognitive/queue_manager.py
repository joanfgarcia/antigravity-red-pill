import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

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
					parent_task_id TEXT DEFAULT NULL,
					created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
					attempts INTEGER NOT NULL DEFAULT 0,
					error_log TEXT
				)
			""")

			# Migración para añadir la columna si la tabla ya existía
			try:
				conn.execute("ALTER TABLE cognitive_tasks ADD COLUMN parent_task_id TEXT DEFAULT NULL")
			except sqlite3.OperationalError:
				pass  # La columna ya existe

			# Migración Job Manager (F1): reanudación nativa de ResumableJobDriver
			for ddl in (
				"ALTER TABLE cognitive_tasks ADD COLUMN checkpoint_data TEXT DEFAULT NULL",
				"ALTER TABLE cognitive_tasks ADD COLUMN progress TEXT DEFAULT NULL",
			):
				try:
					conn.execute(ddl)
				except sqlite3.OperationalError:
					pass

			# Migración Forge (2026-08-05): mission_id para aislamiento entre forges.
			# Almacena el payload[mission_id] de jobs mecánicos (dag_job, agentic_job)
			# para filtrar/aislar misiones sin parsear payloads en cada consulta.
			try:
				conn.execute("ALTER TABLE cognitive_tasks ADD COLUMN mission_id TEXT DEFAULT NULL")
			except sqlite3.OperationalError:
				pass

			# Índice para extracción ultrarrápida del router
			conn.execute("""
				CREATE INDEX IF NOT EXISTS idx_queue_routing
				ON cognitive_tasks(status, priority DESC, created_at ASC)
			""")

	def enqueue_task(
		self, source: str, payload: Dict[str, Any], priority: int = 5, parent_task_id: Optional[str] = None, mission_id: Optional[str] = None
	) -> str:
		"""Inyecta un estímulo/tarea en la cola cognitiva. Si tiene un parent_task_id, entra como BLOCKED.

		`mission_id`: grupo de aislamiento entre forges (misiones independientes).
		Si no se pasa, se lee de `payload["mission_id"]` — así los callers que ya
		llevan la clave en el payload no tienen que duplicarla.
		"""
		task_id = str(uuid.uuid4())
		payload_str = json.dumps(payload)
		initial_status = "BLOCKED" if parent_task_id else "PENDING"
		mission = mission_id or payload.get("mission_id")

		with self._get_connection() as conn:
			conn.execute(
				"""
				INSERT INTO cognitive_tasks (id, source, priority, payload, status, parent_task_id, mission_id)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				""",
				(task_id, source, priority, payload_str, initial_status, parent_task_id, mission),
			)
		logger.debug(f"[QUEUE] Task {task_id} injected (Priority {priority}, Status {initial_status}). Source: {source}")
		return task_id

	def has_pending(self, source: Optional[str] = None) -> bool:
		"""O(1) non-destructive check for pending tasks. Does NOT pop or lock."""
		with self._get_connection() as conn:
			if source:
				row = conn.execute(
					"SELECT 1 FROM cognitive_tasks WHERE status = 'PENDING' AND source = ? LIMIT 1",
					(source,),
				).fetchone()
			else:
				row = conn.execute("SELECT 1 FROM cognitive_tasks WHERE status = 'PENDING' LIMIT 1").fetchone()
			return row is not None

	def find_task_by_payload_key(self, source: str, key: str, value: str) -> Optional[Dict[str, Any]]:
		"""Find a task by a key in its JSON payload. Used for exclusion checks (e.g. compaction dedup)."""
		with self._get_connection() as conn:
			cursor = conn.execute(
				"""
				SELECT id, source, status, payload
				FROM cognitive_tasks
				WHERE source = ? AND status IN ('PENDING', 'PROCESSING')
				ORDER BY created_at DESC LIMIT 10
				""",
				(source,),
			)
			for row in cursor:
				try:
					payload = json.loads(row["payload"])
					if payload.get(key) == value:
						return {"id": row["id"], "source": row["source"], "status": row["status"], "payload": payload}
				except (json.JSONDecodeError, KeyError):
					continue
		return None

	def pop_next_task(
		self,
		allowed_sources: Optional[List[str]] = None,
		exclude_sources: Optional[List[str]] = None,
		exclude_ids: Optional[List[str]] = None,
	) -> Optional[Dict[str, Any]]:
		"""
		Extrae la tarea de mayor prioridad, filtrando por origen si se especifica.
		Marca como PROCESSING atómicamente.
		Retorna la tarea o None si la cola está vacía.

		exclude_ids: ids a saltar en esta pasada (jobs diferidos por entorno —
		la ordenación determinista los devolvería como top en bucle estéril).
		"""
		query = """
			SELECT id, source, priority, payload, attempts, checkpoint_data
			FROM cognitive_tasks
			WHERE status = 'PENDING'
		"""
		params = []
		if allowed_sources is not None:
			if not allowed_sources:
				return None
			placeholders = ",".join(["?"] * len(allowed_sources))
			query += f" AND source IN ({placeholders})"
			params.extend(allowed_sources)
		if exclude_sources is not None:
			if exclude_sources:
				placeholders = ",".join(["?"] * len(exclude_sources))
				query += f" AND source NOT IN ({placeholders})"
				params.extend(exclude_sources)
		if exclude_ids:
			placeholders = ",".join(["?"] * len(exclude_ids))
			query += f" AND id NOT IN ({placeholders})"
			params.extend(exclude_ids)

		query += " ORDER BY priority DESC, created_at ASC LIMIT 1"

		with self._get_connection() as conn:
			conn.execute("BEGIN EXCLUSIVE")
			cursor = conn.execute(query, params)
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

			checkpoint_raw = row["checkpoint_data"]
			return {
				"id": task_id,
				"source": row["source"],
				"priority": row["priority"],
				"attempts": row["attempts"],
				"payload": json.loads(row["payload"]),
				"checkpoint_data": json.loads(checkpoint_raw) if checkpoint_raw else {},
			}

	def _update_curiosity_rating(self, task_id: str, success: bool) -> None:
		"""Actualiza las calificaciones de curiosidad en base al resultado de la ejecución."""
		try:
			from red_pill.config import get_config

			if not getattr(get_config(), "CURIOSITY_ENGINE_ENABLED", True):
				return

			# 1. Obtener la tarea para extraer su payload y categoría
			with self._get_connection() as conn:
				cursor = conn.execute("SELECT payload, source FROM cognitive_tasks WHERE id = ?", (task_id,))
				row = cursor.fetchone()
				if not row:
					return
				# El rating de curiosidad pertenece al carril cognitivo: los jobs
				# mecánicos no deben alimentarlo (su categoría desconocida caería
				# al fallback dynamic_spark e inflaría el rating).
				if row["source"] != "drive_evaluator":
					return
				payload = json.loads(row["payload"])

			category = payload.get("category")
			if not category:
				# Mapeo de respaldo basado en la acción
				action = payload.get("action")
				if action == "orchestrate_minions":
					category = "minion_maintenance"
				elif action == "autonomous_research":
					category = "strategic_synthesis"
				elif action == "spawn_mcp_subagent":
					category = "proactive_coding"
				elif action == "autonomous_ingestion":
					category = "active_learning"
				elif action == "run_command" and "graphify" in payload.get("command", ""):
					category = "graphify_sync"
				else:
					category = "dynamic_spark"

			# 2. Cargar calificaciones
			from red_pill.core.paths import get_state_dir

			curiosity_file = get_state_dir() / "curiosity_ratings.json"
			if not curiosity_file.exists():
				return

			with open(curiosity_file, "r") as f:
				ratings = json.load(f)

			profile_name = getattr(get_config(), "CURIOSITY_PROFILE", "balanced")
			if profile_name not in ratings:
				ratings[profile_name] = {}

			profile_ratings = ratings[profile_name]
			cat_data = profile_ratings.get(category)
			if not cat_data:
				# Si no existe, lo inicializamos para este perfil
				cat_data = {"rating": 25.0, "uncertainty": 8.33, "last_rho": 0.5, "executed_count": 0}
				profile_ratings[category] = cat_data

			# 3. Calcular recompensa en base al resultado (rho)
			rho = 1.0 if success else 0.0
			if not success:
				teacher_reward = -0.5
			else:
				# Las chispas dinámicas ganan recompensa de curiosidad positiva.
				# Las tareas fijas exitosas obtienen 0.0, permitiendo que su prioridad
				# decante al agotarse la incertidumbre (evita inflación de tareas triviales).
				teacher_reward = 0.5 if category == "dynamic_spark" else 0.0

			rating = cat_data.get("rating", 25.0)
			uncertainty = cat_data.get("uncertainty", 8.33)
			executed_count = cat_data.get("executed_count", 0) + 1

			# Actualización estilo TrueSkill simplificado
			lr = 0.5
			new_rating = max(10.0, min(100.0, rating + (lr * teacher_reward * uncertainty)))
			new_uncertainty = max(2.0, uncertainty * 0.9)

			cat_data["rating"] = round(new_rating, 2)
			cat_data["uncertainty"] = round(new_uncertainty, 2)
			cat_data["last_rho"] = rho
			cat_data["executed_count"] = executed_count

			profile_ratings[category] = cat_data
			ratings[profile_name] = profile_ratings

			with open(curiosity_file, "w") as f:
				json.dump(ratings, f, indent=4)

			logger.info(
				f"[CURIOSITY] Category '{category}' updated: rating={new_rating:.2f}, uncertainty={new_uncertainty:.2f}, reward={teacher_reward:.2f}"
			)

		except Exception as e:
			logger.warning(f"[CURIOSITY] Failed to update curiosity ratings: {e}")

	def mark_completed(self, task_id: str) -> None:
		"""Marca una tarea como finalizada exitosamente y desbloquea tareas hijas (Flujo DAG)."""
		self._update_curiosity_rating(task_id, success=True)
		with self._get_connection() as conn:
			conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
				WHERE id = ?
				""",
				(task_id,),
			)
			# DAG: Desbloquear dependencias
			cursor = conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = 'PENDING', updated_at = CURRENT_TIMESTAMP
				WHERE parent_task_id = ? AND status = 'BLOCKED'
				""",
				(task_id,),
			)
			unlocked_count = cursor.rowcount
			if unlocked_count > 0:
				logger.debug(f"[QUEUE-DAG] Task {task_id} completed. Unlocked {unlocked_count} child tasks.")

	def mark_failed(self, task_id: str, error_msg: str) -> None:
		"""
		Marca un fallo. Incrementa intentos.
		Si attempts > 3, activa el disyuntor y la etiqueta como FRUSTRATED.
		"""
		self._update_curiosity_rating(task_id, success=False)
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

	# ── Job Manager (F1): operaciones de ResumableJobDriver ────────────────────

	def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
		"""Fila completa de una tarea (estado, checkpoint, progreso). Para `job status` y R3."""
		with self._get_connection() as conn:
			row = conn.execute("SELECT * FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return None
			task = dict(row)
		for key in ("payload", "checkpoint_data", "progress"):
			if task.get(key):
				try:
					task[key] = json.loads(task[key])
				except (json.JSONDecodeError, TypeError):
					pass
		return task

	def list_tasks(
		self,
		statuses: Optional[List[str]] = None,
		limit: int = 50,
		mission_id: Optional[str] = None,
		mission_prefix: Optional[str] = None,
	) -> List[Dict[str, Any]]:
		"""Listado resumido para `red-pill job list` (activas por defecto, sin payload completo).

		`mission_id`: filtra por el grupo de aislamiento entre forges (solo jobs
		de esa misión). None = todas las misiones.
		`mission_prefix` (D22): filtra por prefijo del mission_id (LIKE) — usado
		por el delivery de Telegram (mission_id `telegram:...`). None = sin filtro.
		"""
		if statuses is None:
			statuses = ["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED", "FRUSTRATED"]
		placeholders = ",".join(["?"] * len(statuses))
		query = f"""
			SELECT id, source, priority, status, attempts, progress, updated_at, mission_id,
				json_extract(payload, '$.title') AS title,
				json_extract(checkpoint_data, '$.dirty_kill.reason') AS dirty_kill
			FROM cognitive_tasks
			WHERE status IN ({placeholders})
			"""
		params: List = list(statuses)
		if mission_id is not None:
			query += " AND mission_id = ?"
			params.append(mission_id)
		if mission_prefix is not None:
			query += " AND mission_id LIKE ? || '%'"
			params.append(mission_prefix)
		query += " ORDER BY status = 'PROCESSING' DESC, status = 'PAUSING' DESC, priority DESC, created_at ASC LIMIT ?"
		params.append(limit)

		with self._get_connection() as conn:
			rows = conn.execute(query, params).fetchall()
		tasks = []
		for row in rows:
			task = dict(row)
			if task.get("progress"):
				try:
					task["progress"] = json.loads(task["progress"])
				except (json.JSONDecodeError, TypeError):
					pass
			tasks.append(task)
		return tasks

	def job_health(self, sources: List[str], stuck_after_seconds: int = 1800) -> Dict[str, int]:
		"""Salud del carril mecánico (solo lectura, para el DaemonPlugin job_monitor):
		jobs PROCESSING sin latido reciente y jobs FRUSTRATED (disyuntor activado)."""
		if not sources:
			return {"stuck": 0, "frustrated": 0}
		placeholders = ",".join(["?"] * len(sources))
		with self._get_connection() as conn:
			stuck = conn.execute(
				f"""
				SELECT COUNT(*) FROM cognitive_tasks
				WHERE status = 'PROCESSING' AND source IN ({placeholders})
					AND updated_at < datetime('now', ?)
				""",
				(*sources, f"-{int(stuck_after_seconds)} seconds"),
			).fetchone()[0]
			frustrated = conn.execute(
				f"SELECT COUNT(*) FROM cognitive_tasks WHERE status = 'FRUSTRATED' AND source IN ({placeholders})",
				(*sources,),
			).fetchone()[0]
		return {"stuck": stuck, "frustrated": frustrated}

	def purge_hygiene(self, completed_days: int = 7, frustrated_days: int = 14, stale_processing_hours: int = 24) -> Dict[str, int]:
		"""Autolimpieza de la cola (invocada por el JanitorMinion nocturno):

		- borra COMPLETED con más de `completed_days` días;
		- borra FRUSTRATED con más de `frustrated_days` días (dead-letter caducado);
		- PROCESSING sin latido > `stale_processing_hours` = colgado → FRUSTRATED, visible en `job list` hasta que la purga lo retire. El carril mecánico nunca llega aquí (requeue_stale lo recupera a los 15 min); esto caza los huérfanos de los demás carriles (samantha, cognitivo).

		Nunca toca PENDING, PAUSED ni BLOCKED. Devuelve contadores por operación.
		"""
		with self._get_connection() as conn:
			completed = conn.execute(
				"DELETE FROM cognitive_tasks WHERE status = 'COMPLETED' AND updated_at < datetime('now', ?)",
				(f"-{int(completed_days)} days",),
			).rowcount
			frustrated = conn.execute(
				"DELETE FROM cognitive_tasks WHERE status = 'FRUSTRATED' AND updated_at < datetime('now', ?)",
				(f"-{int(frustrated_days)} days",),
			).rowcount
			stuck = conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = 'FRUSTRATED',
					error_log = COALESCE(error_log, '') || ' [queue_hygiene: colgado en PROCESSING > ' || ? || 'h]',
					updated_at = CURRENT_TIMESTAMP
				WHERE status = 'PROCESSING' AND updated_at < datetime('now', ?)
				""",
				(int(stale_processing_hours), f"-{int(stale_processing_hours)} hours"),
			).rowcount
		if completed or frustrated or stuck:
			logger.info(f"[QUEUE-HYGIENE] purged completed={completed} frustrated={frustrated}, stuck→FRUSTRATED={stuck}")
		return {"completed_purged": completed, "frustrated_purged": frustrated, "stuck_marked": stuck}

	def purge_task(self, task_id: str, force: bool = False) -> bool:
		"""Retira una fila de la cola por orden del operador (`job purge`).

		Solo estados terminales — FRUSTRATED y COMPLETED; PAUSED únicamente con
		`force` (un pausado es trabajo reanudable, no basura). PENDING/PROCESSING
		jamás: un job vivo se pausa o se abate, nunca se borra debajo del runner.
		Complementa a purge_hygiene (temporal, nocturna): esto es la versión en
		caliente y dirigida.
		"""
		allowed = ("FRUSTRATED", "COMPLETED", "PAUSED") if force else ("FRUSTRATED", "COMPLETED")
		placeholders = ",".join("?" for _ in allowed)
		with self._get_connection() as conn:
			cursor = conn.execute(
				f"DELETE FROM cognitive_tasks WHERE id = ? AND status IN ({placeholders})",
				(task_id, *allowed),
			)
			return cursor.rowcount > 0

	def purge_terminal(self) -> int:
		"""Barre TODAS las filas FRUSTRATED y COMPLETED de una vez.

		La versión inmediata de purge_hygiene, sin ventana temporal. No toca
		PENDING, PAUSED, BLOCKED ni PROCESSING. Devuelve filas retiradas.
		"""
		with self._get_connection() as conn:
			removed = conn.execute("DELETE FROM cognitive_tasks WHERE status IN ('FRUSTRATED', 'COMPLETED')").rowcount
		if removed:
			logger.info(f"[QUEUE-PURGE] operator purge removed {removed} terminal job(s)")
		return removed

	def save_checkpoint(self, task_id: str, checkpoint: Dict[str, Any], progress: Optional[Dict[str, Any]] = None) -> None:
		"""Persiste el avance atómico tras un step().

		Incondicional sobre el id: el checkpoint es DATO, no estado — si el
		operador pausó a mitad de step, el avance de ese step debe conservarse.
		"""
		with self._get_connection() as conn:
			conn.execute(
				"""
				UPDATE cognitive_tasks
				SET checkpoint_data = ?, progress = ?, updated_at = CURRENT_TIMESTAMP
				WHERE id = ?
				""",
				(json.dumps(checkpoint), json.dumps(progress) if progress is not None else None, task_id),
			)

	def update_checkpoint(self, task_id: str, checkpoint: Dict[str, Any], progress: Optional[Dict[str, Any]] = None) -> bool:
		"""Escribe un checkpoint en un job (handoff de control transferible).

		El puente del handoff: cuando el main-loop toma el control de un
		dag_job, ejecuta N pasos inline y escribe aquí el nuevo checkpoint
		(`step_index` avanzado). El job debe estar PAUSED/PENDING — un job en
		vuelo (PROCESSING) no se toca: el runner persiste sus propios checkpoints
		tras cada step (R4). Devuelve True si se aplicó.
		"""
		with self._get_connection() as conn:
			row = conn.execute("SELECT status FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return False
			if row["status"] in ("PROCESSING", "PAUSING"):
				return False
			if progress is not None:
				conn.execute(
					"UPDATE cognitive_tasks SET checkpoint_data = ?, progress = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
					(json.dumps(checkpoint), json.dumps(progress), task_id),
				)
			else:
				# Handoff sin progress: preservar el existente (borrarlo a NULL
				# destruye step_seconds_ema y descalibra la cota del runner).
				conn.execute(
					"UPDATE cognitive_tasks SET checkpoint_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
					(json.dumps(checkpoint), task_id),
				)
			return True

	def mark_dirty_kill(self, task_id: str, marker: Dict[str, Any]) -> None:
		"""Sella el checkpoint como interrumpido en duro (kill del operador o timeout).

		No es un estado nuevo: el job sigue siendo reanudable con el mismo verbo,
		pero la marca viaja con él para que el driver valide el estado del
		satélite antes de relanzar (y para el análisis forense posterior). La
		limpia el propio driver al devolver checkpoint fresco tras un step bueno.
		"""
		with self._get_connection() as conn:
			row = conn.execute("SELECT checkpoint_data FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return
			try:
				checkpoint = json.loads(row["checkpoint_data"]) if row["checkpoint_data"] else {}
			except (json.JSONDecodeError, TypeError):
				checkpoint = {}
			checkpoint["dirty_kill"] = {**marker, "at": time.time()}
			conn.execute(
				"UPDATE cognitive_tasks SET checkpoint_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
				(json.dumps(checkpoint), task_id),
			)

	def set_checkpoint_key(self, task_id: str, key: str, value: Any) -> None:
		"""Read-modify-write de una clave del checkpoint (D22/D19).

		A diferencia de `update_checkpoint()` — que REEMPLAZA el JSON completo y
		destruiría `checkpoint_data.response` — este método añade/actualiza una
		sola clave preservando el resto. Patrón de `mark_dirty_kill()`. Lo usa el
		delivery de Telegram para sellar `telegram_delivered` sin tocar `response`.
		"""
		with self._get_connection() as conn:
			row = conn.execute("SELECT checkpoint_data FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return
			try:
				checkpoint = json.loads(row["checkpoint_data"]) if row["checkpoint_data"] else {}
			except (json.JSONDecodeError, TypeError):
				checkpoint = {}
			checkpoint[key] = value
			conn.execute(
				"UPDATE cognitive_tasks SET checkpoint_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
				(json.dumps(checkpoint), task_id),
			)

	def kill_task(self, task_id: str, discard: bool = False) -> bool:
		"""Interrupción dura: sella el estado ANTES de abatir el proceso.

		El orden importa — si el runner viera el rc≠0 antes de que la fila diga
		PAUSED, trataría el kill del operador como un fallo real y le quemaría un
		intento del disyuntor. Con `discard`, el job no vuelve: queda FRUSTRATED
		con su motivo, visible en `job list` hasta que la higiene nocturna lo retire
		(la trazabilidad vale más que borrar la fila en caliente).

		PAUSING se incluye en el filtro: es un estado transitorio entre PROCESSING
		y PAUSED (R3: operador pausa a mitad de step, runner termina el step
		actual antes de soltar). Si el operador mata en ese intervalo, la pausa
		prevalece y debe poder convertirse en PAUSED/FRUSTRATED sin esperar al
		checkpoint del runner.
		"""
		self.mark_dirty_kill(task_id, {"reason": "operator"})
		status, error_log = ("FRUSTRATED", "cancelled by operator") if discard else ("PAUSED", None)
		with self._get_connection() as conn:
			cursor = conn.execute(
				"""
				UPDATE cognitive_tasks
				SET status = ?, error_log = COALESCE(?, error_log), updated_at = CURRENT_TIMESTAMP
				WHERE id = ? AND status IN ('PENDING', 'PROCESSING', 'PAUSED', 'PAUSING')
				""",
				(status, error_log, task_id),
			)
			return cursor.rowcount > 0

	def pause_task(self, task_id: str) -> bool:
		"""Solicitud de pausa del operador.

		- PENDING → PAUSED (sin step en vuelo, pausa inmediata).
		- PROCESSING → PAUSING (step en vuelo; el runner pausará al alcanzar la frontera del step).
		Devuelve True si la pausa fue aplicada/solicitada, o False si no aplica.
		"""
		with self._get_connection() as conn:
			row = conn.execute("SELECT status FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return False
			current_status = row["status"]
			if current_status == "PENDING":
				conn.execute("UPDATE cognitive_tasks SET status = 'PAUSED', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
				return True
			elif current_status == "PROCESSING":
				conn.execute("UPDATE cognitive_tasks SET status = 'PAUSING', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
				return True
			return False

	def mark_paused(self, task_id: str) -> bool:
		"""Sella la pausa definitiva cuando el runner alcanza la frontera del step (PAUSING/PROCESSING → PAUSED)."""
		with self._get_connection() as conn:
			cursor = conn.execute(
				"UPDATE cognitive_tasks SET status = 'PAUSED', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN ('PAUSING', 'PROCESSING', 'PENDING')",
				(task_id,),
			)
			return cursor.rowcount > 0

	def resume_task(self, task_id: str) -> bool:
		"""Reanuda o cancela la pausa de un job.

		- PAUSING → PROCESSING: cancela la solicitud de pausa en vuelo antes del fin del step.
		- PAUSED / FRUSTRATED / stuck PROCESSING (>900s) → PENDING: reanuda en el siguiente disparo del runner.
		Devuelve True si se reanudó/canceló la pausa, o False si no aplica.
		"""
		with self._get_connection() as conn:
			row = conn.execute("SELECT status, updated_at FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
			if not row:
				return False
			current_status = row["status"]

			# Cancelación de pausa en caliente: el job está corriendo en PAUSING
			if current_status == "PAUSING":
				conn.execute("UPDATE cognitive_tasks SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
				return True

			# Reanudación desde estado detenido
			cursor = conn.execute(
				"""
				UPDATE cognitive_tasks SET status = 'PENDING', attempts = 0, updated_at = CURRENT_TIMESTAMP
				WHERE id = ? AND (
					status IN ('PAUSED', 'FRUSTRATED')
					OR (status = 'PROCESSING' AND updated_at < datetime('now', '-900 seconds'))
				)
				""",
				(task_id,),
			)
			return cursor.rowcount > 0

	def has_higher_priority_pending(self, sources: List[str], priority: int) -> bool:
		"""¿Espera un job PENDING de los carriles dados con prioridad ESTRICTAMENTE mayor?

		Alimenta la cesión en frontera de step del runner: la prioridad de la cola
		solo ordena pops, y un job de múltiples steps (un entrenamiento de días)
		monopolizaría el runner — el sueño de las 03:00 no puede esperar a que la
		escuela complete. Acotado a los sources de drivers: el carril cognitivo
		jamás desaloja a nadie.
		"""
		if not sources:
			return False
		placeholders = ",".join(["?"] * len(sources))
		with self._get_connection() as conn:
			row = conn.execute(
				f"SELECT 1 FROM cognitive_tasks WHERE status = 'PENDING' AND priority > ? AND source IN ({placeholders}) LIMIT 1",
				[priority, *sources],
			).fetchone()
		return row is not None

	def defer_task(self, task_id: str) -> bool:
		"""Deferral por entorno no disponible (VRAM/IDE/SIP): PROCESSING → PENDING
		SIN incrementar attempts (R1 — el disyuntor es para fallos reales del job).
		Condicional sobre PROCESSING: una pausa del operador a mitad de step gana (R3)."""
		with self._get_connection() as conn:
			cursor = conn.execute(
				"UPDATE cognitive_tasks SET status = 'PENDING', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'PROCESSING'",
				(task_id,),
			)
			return cursor.rowcount > 0

	def requeue_stale(self, sources: List[str], older_than_seconds: int = 900) -> int:
		"""Recupera huérfanos PROCESSING de un crash del runner → PENDING con attempts+1.

		ACOTADA por source (R5): el carril cognitivo deja PROCESSING colgando a
		propósito (el agente reporta por MCP) y jamás debe resetearse desde aquí.
		"""
		if not sources:
			return 0
		placeholders = ",".join(["?"] * len(sources))
		with self._get_connection() as conn:
			cursor = conn.execute(
				f"""
				UPDATE cognitive_tasks
				SET status = 'PENDING', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
				WHERE status = 'PROCESSING' AND source IN ({placeholders})
					AND updated_at < datetime('now', ?)
				""",
				(*sources, f"-{int(older_than_seconds)} seconds"),
			)
			recovered = cursor.rowcount
		if recovered:
			logger.warning(f"[QUEUE] Recovered {recovered} stale PROCESSING job(s) from sources {sources}.")
		return recovered
