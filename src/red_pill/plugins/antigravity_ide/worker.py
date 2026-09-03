import json
import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from red_pill.core.paths import get_config_dir, get_neon_link_config_dir, get_neon_link_db_path, get_state_dir

# Cargar la configuración agnóstica de Neon-Link primero (Single Source of Truth)
neon_link_config = get_neon_link_config_dir() / ".env"
if neon_link_config.exists():
	load_dotenv(neon_link_config)

# Cargar la configuración centralizada de Red-Pill
red_pill_config = get_config_dir() / ".env"
if red_pill_config.exists():
	load_dotenv(red_pill_config)

load_dotenv()  # Override local si existiera

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from ide_client import AntigravityIDEClient  # noqa: E402

import red_pill.config as cfg  # noqa: E402
from red_pill.swarm.bridges import (  # noqa: E402
	AgentBridge,  # noqa: E402
	AllModelsExhausted,
	BackendType,
	BridgeCapabilities,
	NoModelsConfigured,
	create_cascade_bridge,
)

logger = logging.getLogger(__name__)

# Alineación con el estándar de Sovereign Gateway (Neon-Link)
default_db = get_neon_link_db_path()
DB_PATH = Path(os.environ.get("NEON_LINK_DB_PATH", default_db))


# Budget guard defaults
MAX_AWAKENINGS_PER_DAY = 8
AWAKENING_TIMEOUT = 600
AWAKENING_MAX_TOOL_CALLS = 40


def get_connection():
	conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA synchronous=NORMAL;")
	# Execution ledger for budget guard
	conn.execute(
		"CREATE TABLE IF NOT EXISTS execution_ledger ("
		"id INTEGER PRIMARY KEY AUTOINCREMENT, "
		"exec_type TEXT NOT NULL, "
		"conversation_id TEXT, "
		"started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
		"duration_s REAL, "
		"response_len INTEGER DEFAULT 0, "
		"status TEXT DEFAULT 'started'"
		")"
	)
	return conn


def _format_cascade_error(exc: Exception) -> str:
	"""Build a user-facing Telegram message for an exhausted bridge cascade."""
	if isinstance(exc, NoModelsConfigured):
		return "⚠️ No hay ningún modelo configurado para atender el mensaje (TELEGRAM_BRIDGE_CASCADE vacío)."
	errors = getattr(exc, "errors", None)
	if errors:
		lines = "\n".join(f"• {t.backend}/{t.model or 'default'}: {msg}" for t, msg in errors)
		return f"⚠️ No pude atender tu mensaje — ningún modelo disponible:\n{lines}"
	return f"⚠️ No pude atender tu mensaje: {exc}"


def _is_bridge_timeout(exc: Exception) -> bool:
	"""Classify a bridge failure as a TIMEOUT (D24).

	Bridge backends surface timeouts as `RuntimeError("... timed out after Ns")`
	(raised from `subprocess.TimeoutExpired`). Anything else — spawn failures,
	network errors, 5xx, quota messages — is transient, NOT a timeout.
	"""
	import subprocess

	if isinstance(exc, subprocess.TimeoutExpired):
		return True
	text = str(exc).lower()
	return isinstance(exc, RuntimeError) and ("timed out" in text or "timeout" in text)


def _emit_d24_pain_signal(msg_ids, error_text: str) -> None:
	"""D24 req. operador: if a timeout is NOT classified as such (and thus retried
	with cap 3 instead of cap 1), emit a typed pain signal so someone investigates.
	Dedup via has_signal to avoid spamming every pulse."""
	try:
		from red_pill.memory import MemoryManager

		mm = MemoryManager()
		name = "telegram_timeout_cap1_not_applied"
		if mm.has_signal(name):
			return
		mm.inject_signal(
			name=name,
			intensity=6.0,
			signal_type="pain",
			source="TelegramWorker",
			originator="worker._process_via_bridge",
			criticality="WARNING",
			message=f"Timeout del bridge clasificado como transitorio (cap 3 en vez de cap 1). msgs={msg_ids}. error={error_text[:300]}",
		)
	except Exception as e:
		logger.warning(f"[D24] Failed to emit pain signal: {e}")


def _detect_routing_keyword(text: str) -> Optional[str]:
	"""Detect an explicit routing keyword at the START of a Telegram message
	(D2/D10). Case-insensitive, first token. In Fase 1 this is signal-only:
	the keyword is stripped from the prompt (D10) but execution stays fast path
	(forward-compatible with Fase 2's heavy path).

	Returns the matched keyword ('/mission', '#mission', '#heavy', '#job') or None.
	"""
	if not text:
		return None
	first = text.strip().split(maxsplit=1)[0].lower()
	keywords = {"/mission", "#mission", "#heavy", "#job"}
	return next((k for k in keywords if first == k), None)


def _detect_escalate_marker(response: str, window: int = 64) -> bool:
	"""Detect the [ESCALATE] marker at the START of a model response (D14).
	Parsing is tolerant: the marker must appear within the first `window`
	characters (ratified default 64), allowing for whitespace/prefix noise.
	In Fase 1 this is signal-only — the full response is still delivered.
	"""
	if not response:
		return False
	head = response[:window].upper()
	return "[ESCALATE]" in head


class IDEWorker:
	def __init__(self):
		self.client = AntigravityIDEClient()
		self.running = True
		self._bridge_telegram: AgentBridge | None = None
		self._bridge_awakening: AgentBridge | None = None
		self._bridge_minion: AgentBridge | None = None
		self._caps: BridgeCapabilities = BridgeCapabilities(backend=BackendType.GRPC)
		self._samantha_worker = None
		# AgentBridge: create execution bridges based on config
		try:
			cfg_inst = cfg.get_config()
			telegram_cascade = cfg_inst.TELEGRAM_BRIDGE_CASCADE
			# D5 (Fase 1 guard): local is not capable of heavy work — filter it
			# out of the conversational cascade unless explicitly allowed.
			if not cfg_inst.LOCAL_ALLOWED_FOR_HEAVY and telegram_cascade:
				filtered = [t for t in telegram_cascade if t.backend != "local"]
				if len(filtered) != len(telegram_cascade):
					logger.info("[IDEWorker] D5 guard: filtered local target(s) from TELEGRAM_BRIDGE_CASCADE")
				telegram_cascade = filtered
			self._bridge_telegram = create_cascade_bridge(telegram_cascade, name="TELEGRAM_BRIDGE_CASCADE")
			self._bridge_awakening = create_cascade_bridge(cfg_inst.AWAKENING_BRIDGE_CASCADE, name="AWAKENING_BRIDGE_CASCADE", origin="awakening")
			self._bridge_minion = create_cascade_bridge(cfg_inst.DEFAULT_MINION_BRIDGE_CASCADE, name="DEFAULT_MINION_BRIDGE_CASCADE")

			# Fallback for capabilities / legacy checks
			self._caps = self._bridge_telegram.get_capabilities()
			logger.info(f"[IDEWorker] Telegram Bridge: {self._bridge_telegram.get_capabilities().backend.value.upper()}")
			logger.info(f"[IDEWorker] Awakening Bridge: {self._bridge_awakening.get_capabilities().backend.value.upper()}")
			logger.info(f"[IDEWorker] Minion Bridge: {self._bridge_minion.get_capabilities().backend.value.upper()}")
		except Exception as e:
			logger.warning(f"[IDEWorker] Bridge creation failed, falling back to gRPC-only: {e}")
			from red_pill.swarm.bridges.factory import create_bridge

			self._bridge_telegram = create_bridge("grpc")
			self._bridge_awakening = create_bridge("grpc")
			self._bridge_minion = create_bridge("grpc")
			self._caps = self._bridge_telegram.get_capabilities()
		# SamanthaWorker: background thread for local LLM tasks (non-blocking)
		try:
			from red_pill.inference.samantha_worker import SamanthaWorker

			self._samantha_worker = SamanthaWorker()
			self._samantha_worker.start()
			logger.info("[IDEWorker] SamanthaWorker thread started")
		except Exception as e:
			logger.warning(f"[IDEWorker] SamanthaWorker init failed (local LLM tasks disabled): {e}")

		# D21: decoupled heartbeat thread + activity lease. The main pulse can
		# block on a 300s bridge call; the heartbeat must keep beating DURING it
		# or neon-link (60s threshold) declares a false "Córtex Offline". A dead
		# main loop stops touching the lease → it expires (HEARTBEAT_LEASE) →
		# the thread stops beating → real offline is still detected.
		self._lease_lock = threading.Lock()
		self._lease_touch = time.monotonic()
		self._heartbeat_thread = threading.Thread(
			target=self._heartbeat_thread_main,
			name="heartbeat-daemon",
			daemon=True,
		)
		self._heartbeat_thread.start()
		logger.info("[IDEWorker] Heartbeat thread started (D21, lease=%ss)", cfg.get_config().HEARTBEAT_LEASE)

	def _touch_lease(self):
		"""Record worker activity. The heartbeat thread only beats while the lease
		is fresh — a healthy main loop keeps touching at every pulse boundary and
		before every bridge call."""
		try:
			with self._lease_lock:
				self._lease_touch = time.monotonic()
		except Exception as e:
			logger.debug(f"[IDEWorker] lease touch failed: {e}")

	def _heartbeat_thread_main(self):
		"""Daemon thread: update system_health while the process lives and the
		lease is fresh. Falls silent when the main loop is dead (lease expired) so
		real offline is detectable. Uses its own connection to avoid sharing the
		pulse's write transaction (D23)."""
		lease = cfg.get_config().HEARTBEAT_LEASE
		while True:
			try:
				with self._lease_lock:
					fresh = (time.monotonic() - self._lease_touch) < lease
				if fresh:
					self.update_heartbeat()
				time.sleep(20)
			except Exception as e:
				logger.warning(f"[IDEWorker] Heartbeat thread error: {e}")
				time.sleep(20)

	def run(self):
		logger.info("Red-Pill AntigravityIDEPlugin Worker started.")
		while self.running:
			try:
				self.run_once()
				time.sleep(2)
			except KeyboardInterrupt:
				logger.info("Shutting down worker...")
				self.running = False
			except Exception as e:
				logger.error(f"Worker exception: {e}")
				time.sleep(5)

	def run_once(self):
		# D21: touch the heartbeat lease at the start of each pulse — the
		# heartbeat thread only beats while this stays fresh.
		self._touch_lease()
		# Containment: one poisoned inbox item must not kill the pulse (and with
		# it the heartbeat that neon-link watches to report Córtex Offline).
		try:
			self.process_inbox()
		except Exception:
			logger.exception("[IDEWorker] process_inbox failed — pulse continues")
		# Fase 2: entrega de resultados de jobs Telegram (D18/D19) en cada pulse.
		try:
			self._check_telegram_jobs()
		except Exception:
			logger.exception("[IDEWorker] _check_telegram_jobs failed — pulse continues")
		legacy_grpc = not self._caps or self._caps.backend == BackendType.GRPC
		if legacy_grpc and cfg.get_config().TELEGRAM_BRIDGE_CASCADE:
			# Degraded capabilities with a configured cascade mean every bridge
			# failed to construct (see cascade construction errors at boot). The
			# IDE polling path is Antigravity-only — never resurrect it here.
			# Log once, not on every 2s pulse.
			if not getattr(self, "_cascade_degraded_logged", False):
				self._cascade_degraded_logged = True
				logger.error("[IDEWorker] TELEGRAM_BRIDGE_CASCADE set but no bridge could be built; skipping legacy IDE polling.")
			legacy_grpc = False
		if legacy_grpc:
			try:
				self.check_for_replies()
				self.check_minion_inbox_auto_inject()
				self.process_cognitive_queue()
			except Exception:
				logger.exception("[IDEWorker] legacy IDE polling failed — pulse continues")
		else:
			# Autonomous agy operations (minion auto-inject, cognitive queue)
			# are gated behind AUTONOMOUS_AGY_ENABLED to prevent Flash quota
			# drain. Telegram inbox processing above is NOT affected.
			if cfg.get_config().AUTONOMOUS_AGY_ENABLED:
				self.check_minion_inbox_auto_inject_agy()
				self.process_cognitive_queue_agy()
			# Janitor sweep for local telegram sessions
			try:
				from telegram_session import TelegramSessionManager

				tsm = TelegramSessionManager()
				purged = tsm.run_janitor_sweep()
				if purged > 0:
					logger.info(f"[Janitor] Sweep complete. Purged {purged} archived conversations.")
			except Exception as e:
				logger.error(f"Janitor sweep failed: {e}")
			# Samantha Queue: signal worker if there are pending tasks (NON-BLOCKING)
			self._signal_samantha_worker()
		# Watchdog: verify SamanthaWorker thread health
		self._watchdog_samantha()
		self.update_heartbeat()

	def update_heartbeat(self):
		conn = get_connection()
		conn.execute("UPDATE system_health SET last_heartbeat = CURRENT_TIMESTAMP WHERE service_name = 'red_pill'")
		conn.commit()
		conn.close()

	def _handle_retry_failure(
		self,
		msg_ids,
		channel,
		channel_user_id,
		cursor,
		exc: Optional[Exception] = None,
		error_text: Optional[str] = None,
	) -> bool:
		"""Increment retries with a cap by error class (D24).

		Timeout → ONE retry allowed: the second timeout is DEAD (the same prompt
		would burn the timeout again, blocking the pulse ~300s more and tripling
		token cost). Transient errors (spawn/red/5xx) → cap 3 as before.

		When the cap is reached: mark inbox DEAD, write the dead_letters row
		(D12), and notify the user via outbox.

		Returns True when the message was killed (DEAD), False otherwise.
		"""
		text = error_text or (str(exc) if exc else "unknown error")
		is_timeout = _is_bridge_timeout(exc) if exc else "timed out" in (text or "").lower()

		# D24 signal de dolor: if the failure LOOKS like a timeout but was NOT
		# classified as one (classifier miss), the cap would wrongly be higher → flag it.
		looks_like_timeout = "timed out" in (text or "").lower() or "timeout" in (text or "").lower()
		if looks_like_timeout and not is_timeout:
			_emit_d24_pain_signal(msg_ids, text)

		# Cap in terms of the retries counter: timeout allows ONE retry (the
		# second timeout → DEAD, so retries>=2 kills it); transients keep the
		# legacy cap 3 (retries>=3 → DEAD). Mirrors diagram 4.5 for transients.
		cap = 2 if is_timeout else 3

		for m_id in msg_ids:
			row = cursor.execute("SELECT retries FROM inbox WHERE id = ?", (m_id,)).fetchone()
			retries = (row["retries"] if row else 0) + 1
			if retries >= cap:
				logger.error(f"[{msg_ids}] Retries exhausted (cap={cap}, class={'timeout' if is_timeout else 'transient'}) for msg {m_id}: {text}")
				cursor.execute("UPDATE inbox SET status = 'DEAD', retries = ? WHERE id = ?", (retries, m_id))
				# D12: write to the dead_letters table (neon-link events.db)
				try:
					orig = cursor.execute("SELECT payload FROM inbox WHERE id = ?", (m_id,)).fetchone()
					payload = orig["payload"] if orig else None
					cursor.execute(
						"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) "
						"VALUES ('inbox', ?, ?, ?, ?, ?)",
						(m_id, channel, channel_user_id, payload, text[:500]),
					)
				except Exception as e:
					logger.warning(f"[{msg_ids}] Failed to write dead_letter for {m_id}: {e}")
				if channel != "system":
					cursor.execute(
						"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
						(
							channel,
							channel_user_id,
							None,
							json.dumps(
								{
									"text": "⚠️ Tu mensaje no pudo ser procesado tras "
									f"{retries} intento(s). Reintenta con /new o revisa la cola con /queue. "
									"Para prompts ambiciosos, considera prefijar con `/mission` o `#mission`."
								}
							),
						),
					)
			else:
				logger.warning(f"[{msg_ids}] Retry {retries}/{cap} for msg {m_id}: {text}")
				cursor.execute("UPDATE inbox SET retries = ? WHERE id = ?", (retries, m_id))
		return retries >= cap

	def _signal_samantha_worker(self):
		"""NON-BLOCKING: check if there are pending Samantha tasks and signal the worker thread."""
		if not self._samantha_worker:
			return
		try:
			from red_pill.cognitive.queue_manager import CognitiveQueueManager
			from red_pill.inference.samantha_worker import SAMANTHA_SOURCE

			qm = CognitiveQueueManager()
			if qm.has_pending(source=SAMANTHA_SOURCE):
				self._samantha_worker.wake()
		except Exception as e:
			logger.error(f"[IDEWorker] Samantha signal failed: {e}")

	def _watchdog_samantha(self):
		"""Monitor SamanthaWorker thread health. Restart if stuck or dead."""
		if not self._samantha_worker:
			return
		try:
			if not self._samantha_worker.is_alive():
				logger.error("[Watchdog] SamanthaWorker thread died — restarting")
				self._restart_samantha_worker()
			elif not self._samantha_worker.is_healthy():
				logger.error(f"[Watchdog] SamanthaWorker hung (task: {self._samantha_worker._current_task_id}) — killing")
				# Kill ephemeral process if running
				self._samantha_worker.force_kill_ephemeral()
				# Mark current task as frustrated
				if self._samantha_worker._current_task_id:
					try:
						from red_pill.cognitive.queue_manager import CognitiveQueueManager

						qm = CognitiveQueueManager()
						qm.mark_failed(self._samantha_worker._current_task_id, "Watchdog timeout")
					except Exception:
						pass
				# Restart the thread
				self._restart_samantha_worker()
		except Exception as e:
			logger.error(f"[Watchdog] Samantha check failed: {e}")

	def _restart_samantha_worker(self):
		"""Restart the SamanthaWorker thread."""
		try:
			if self._samantha_worker:
				self._samantha_worker.stop()
			from red_pill.inference.samantha_worker import SamanthaWorker

			self._samantha_worker = SamanthaWorker()
			self._samantha_worker.start()
			logger.info("[Watchdog] SamanthaWorker restarted")
		except Exception as e:
			logger.error(f"[Watchdog] SamanthaWorker restart failed: {e}")
			self._samantha_worker = None

	def get_trajectory_data(self, cascade_id):
		resp = requests.post(self.client._url("GetAllCascadeTrajectories"), headers=self.client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {}).get(cascade_id, {})
		return {}

	def get_all_trajectories(self):
		resp = requests.post(self.client._url("GetAllCascadeTrajectories"), headers=self.client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {})
		return {}

	def process_inbox(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		debounce_seconds = cfg.REACTIVE_DEBOUNCE_SECONDS if cfg.REACTIVE_DEBOUNCE_ENABLED else 0

		cursor.execute(
			"""
			SELECT channel_user_id
			FROM inbox
			WHERE status = 'PENDING'
			GROUP BY channel_user_id
			HAVING (strftime('%s', 'now') - strftime('%s', max(created_at))) >= ?
				OR sum(case when payload LIKE '%"command"%' then 1 else 0 end) > 0
			LIMIT 1
			""",
			(debounce_seconds,),
		)
		user_row = cursor.fetchone()

		if not user_row:
			conn.close()
			return

		channel_user_id = user_row["channel_user_id"]
		cursor.execute("SELECT * FROM inbox WHERE status = 'PENDING' AND channel_user_id = ? ORDER BY created_at ASC", (channel_user_id,))
		rows = cursor.fetchall()

		conversational_msgs = []
		background_msgs = []
		for r in rows:
			try:
				p = json.loads(r["payload"])
				mode = p.get("mode", "conversational")
				if mode == "background":
					background_msgs.append(r)
				else:
					conversational_msgs.append(r)
			except Exception:
				conversational_msgs.append(r)

		# Handle Background Messages
		if background_msgs:
			from red_pill.core.inbox import MinionInbox

			inbox = MinionInbox()
			for r in background_msgs:
				msg_id = r["id"]
				try:
					p = json.loads(r["payload"])
					text = p.get("text", "")
					sender_id = p.get("sender_id", r["channel_user_id"])
					channel = r["channel"]

					inbox.drop_report(
						event_id=f"bg_msg_{msg_id}", source=f"NeonLink ({channel})", status="pending", content=f"Message from {sender_id}: {text}"
					)
					cursor.execute("UPDATE inbox SET status = 'DELIVERED_BACKGROUND' WHERE id = ?", (msg_id,))
				except Exception as e:
					logger.error(f"Failed background delivery for msg {msg_id}: {e}")
					cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (msg_id,))
			conn.commit()

		if not conversational_msgs:
			conn.close()
			return

		# Handle Conversational Messages (Compaction)
		first_conv = conversational_msgs[0]
		first_payload = json.loads(first_conv["payload"])
		command = first_payload.get("command")

		# If it's a bridged message, the command might be a JSON string inside 'text'
		if not command and "text" in first_payload:
			try:
				nested = json.loads(first_payload["text"])
				if isinstance(nested, dict) and "command" in nested:
					command = nested["command"]
					first_payload = nested
			except Exception as e:
				logger.error(f"[Worker Debug] json.loads failed: {e} on {first_payload['text']}")

		logger.info(f"[Worker Debug] Extracted command: {command}, payload: {first_payload}")

		channel = first_conv["channel"]

		if command == "LIST_CASCADES":
			from telegram_session import TelegramSessionManager

			tsm = TelegramSessionManager()
			sessions = tsm.list_sessions(channel_user_id)

			cursor.execute("DELETE FROM cascade_mappings WHERE channel_user_id = ?", (channel_user_id,))
			response_text = "🧠 **Sesiones de Telegram Activas:**\n\n"
			if not sessions:
				response_text += "_No hay sesiones activas. Envía un mensaje o /new para crear una._\n"
			else:
				for i, sess in enumerate(sessions[:5]):
					idx = i + 1
					cid = sess["id"]
					title = sess.get("summary", {}).get("summary", "Sin Título")
					cursor.execute(
						"INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES (?, ?, ?)", (channel_user_id, cid, title)
					)
					response_text += f"`[{idx}]` {title}\n"
			response_text += "\nEnvía `/switch <número>` para anclar tu sesión."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": response_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SWITCH_CASCADE":
			idx = first_payload.get("index")
			cursor.execute(
				"SELECT cascade_id, title FROM cascade_mappings WHERE channel_user_id = ? AND id = (SELECT id FROM cascade_mappings WHERE channel_user_id = ? ORDER BY id ASC LIMIT 1 OFFSET ?)",
				(channel_user_id, channel_user_id, idx - 1),
			)
			mapping = cursor.fetchone()
			if mapping:
				cid = mapping["cascade_id"]
				title = mapping["title"]
				cursor.execute(
					"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
					(channel_user_id, cid),
				)
				resp_text = f"🔗 Sesión anclada a: **{title}**.\nTodos los mensajes se inyectarán en esta conversación."
			else:
				resp_text = "❌ Índice no encontrado. Usa `/list` primero."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "NEW_CASCADE":
			from telegram_session import TelegramSessionManager

			tsm = TelegramSessionManager()
			new_session = tsm.create_session(channel_user_id)
			new_id = new_session["id"]

			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type, model, backend) VALUES (?, ?, 'local_session', NULL, NULL)",
				(channel_user_id, new_id),
			)
			resp_text = "✨ Nueva sesión de Telegram inicializada y anclada correctamente.\nEl contexto está a cero. ¿En qué puedo ayudarte?"
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "LIST_MODELS":
			# /models [--backend X] — lista el catálogo curado (D6/D7), sin agente.
			from red_pill.core.model_catalog import ModelCatalog

			try:
				catalog = ModelCatalog()
				models = catalog.models(backend=first_payload.get("backend"))
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Model catalog error: {e}")
				resp_text = f"⚠️ No se pudo leer el catálogo de modelos: {e}"
			else:
				if not models:
					resp_text = "ℹ️ No hay modelos curados."
				else:
					lines = []
					for m in models:
						roles = ", ".join(m.get("roles", []) or []) or "-"
						lines.append(f"• `{m['id']}` — {m.get('tier')} (prio {m.get('priority')}) roles: {roles}")
					resp_text = "🧠 **Modelos curados:**\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SET_MODEL":
			# /model <id> — valida contra el catálogo (D7) y persiste backend del catálogo (D8).
			from red_pill.core.model_catalog import ModelCatalog

			model_id = first_payload.get("model", "").strip()
			try:
				catalog = ModelCatalog()
				entry = catalog.get(model_id)
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Model catalog error: {e}")
				entry = None
			if not entry:
				resp_text = f"❌ El modelo `{model_id}` no está en el catálogo curado. Usa `/models` para ver los disponibles."
			else:
				backend = entry.get("backend")
				cursor.execute(
					"UPDATE telegram_sessions SET model = ?, backend = ? WHERE channel_user_id = ?",
					(model_id, backend, channel_user_id),
				)
				resp_text = f"✅ Modelo de sesión establecido: `{model_id}` (backend `{backend}`)."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SHOW_MODEL":
			cursor.execute("SELECT model, backend FROM telegram_sessions WHERE channel_user_id = ?", (channel_user_id,))
			row = cursor.fetchone()
			if row and row["model"]:
				resp_text = f"🔧 Modelo de sesión actual: `{row['model']}` (backend `{row['backend']}`)."
			else:
				resp_text = "ℹ️ Sin override de modelo — la sesión usa la cascade configurada en `.env`."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "RESET_MODEL":
			cursor.execute("UPDATE telegram_sessions SET model = NULL, backend = NULL WHERE channel_user_id = ?", (channel_user_id,))
			resp_text = "↩️ Override de modelo eliminado — se vuelve a la cascade configurada en `.env`."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SHOW_QUEUE":
			# /queue — estado de la cola central (script tonto, sin agente).
			from red_pill.cognitive.queue_manager import CognitiveQueueManager

			try:
				queue = CognitiveQueueManager()
				tasks = queue.list_tasks(limit=10)
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Queue read error: {e}")
				resp_text = f"⚠️ No se pudo leer la cola: {e}"
			else:
				if not tasks:
					resp_text = "🗂️ La cola de jobs está vacía."
				else:
					lines = []
					for t in tasks:
						title = (t.get("title") or "")[:40]
						lines.append(f"• `{t['id'][:8]}` **{t['status']}** prio={t['priority']} {title}")
					resp_text = "🗂️ **Cola de jobs activos:**\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "LIST_DEFERRED":
			# /deferred — lista mensajes DEFERRED (D13, quota agotada).
			cursor.execute("SELECT id, payload, retries FROM inbox WHERE status = 'DEFERRED' AND channel_user_id = ?", (channel_user_id,))
			rows = cursor.fetchall()
			if not rows:
				resp_text = "ℹ️ No hay mensajes DEFERRED para esta sesión."
			else:
				lines = []
				for r in rows:
					text = ""
					try:
						text = (json.loads(r["payload"]).get("text") or "")[:50]
					except Exception:
						pass
					lines.append(f"• `{r['id']}` (intentos {r['retries']}): {text}")
				resp_text = "📋 **Mensajes DEFERRED** (quota agotada — usa `/model` con un modelo con quota o espera):\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "HEAVY_PATH":
			# /mission <prompt> — fuerza el heavy path (Fase 2): encola agentic_job.
			# Implementación completa en la Fase 2; aquí delega en _enqueue_heavy.
			self._enqueue_heavy_path(
				text=first_payload.get("text", ""),
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=[first_conv["id"]],
				cursor=cursor,
				conn=conn,
			)
			return

		# Build compacted prompt
		buffer_texts = []
		msg_ids_to_process = []
		for cr in conversational_msgs:
			try:
				p = json.loads(cr["payload"])
				text = p.get("text", "")
				buffer_texts.append(text)
				msg_ids_to_process.append(cr["id"])
			except Exception:
				pass

		if not msg_ids_to_process:
			conn.close()
			return

		combined_text = "\n".join(buffer_texts)

		# Handle Delete Command
		combined_text_clean = combined_text.strip()
		if combined_text_clean.startswith("/delete"):
			parts = combined_text_clean.split()
			target_id = None
			title = ""

			from telegram_session import TelegramSessionManager

			tsm = TelegramSessionManager()

			if len(parts) == 2 and parts[1].isdigit():
				idx = int(parts[1])
				cursor.execute(
					"SELECT cascade_id, title FROM cascade_mappings WHERE channel_user_id = ? AND id = (SELECT id FROM cascade_mappings WHERE channel_user_id = ? ORDER BY id ASC LIMIT 1 OFFSET ?)",
					(channel_user_id, channel_user_id, idx - 1),
				)
				mapping = cursor.fetchone()
				if mapping:
					target_id = mapping["cascade_id"]
					title = mapping["title"]
				else:
					resp_text = "❌ Índice no encontrado. Usa `/list` primero."
			else:
				# Delete currently active session
				cursor.execute(
					"SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
					(channel_user_id,),
				)
				session_row = cursor.fetchone()
				if session_row:
					target_id = session_row["cascade_id"]
					sess = tsm.get_session(target_id)
					if sess:
						title = sess.get("summary", {}).get("summary", "Sin Título")
				else:
					resp_text = "❌ No tienes ninguna sesión activa para eliminar."

			if target_id:
				success = tsm.mark_for_deletion(target_id)
				if success:
					cursor.execute(
						"DELETE FROM telegram_sessions WHERE channel_user_id = ? AND cascade_id = ?",
						(channel_user_id, target_id),
					)
					resp_text = f"🗑️ La sesión **{title}** ha sido marcada para eliminación y copiada a la cola de ingesta. Se purgará del disco una vez archivada."
				else:
					resp_text = "❌ Error al intentar eliminar la sesión."

			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		# ---- System channel: AWAKENINGs run in isolation (no Telegram session) ----
		# A configured AWAKENING cascade forces the bridge path even when
		# capabilities degraded (bridge construction failed) — never fall through
		# to the Antigravity-only legacy path on behalf of non-IDE backends.
		if channel == "system" and ((self._caps and self._caps.auto_approve) or cfg.get_config().AWAKENING_BRIDGE_CASCADE):
			self._process_awakening(combined_text, msg_ids_to_process, cursor, conn)
			conn.commit()
			conn.close()
			return

		# ---- Touch idle-detection file for non-AWAKENING messages ----
		# This prevents autonomous_cron from thinking the operator is idle
		# when they are actively chatting via Telegram.
		try:
			activity_file = get_state_dir() / "last_user_activity.txt"
			activity_file.parent.mkdir(parents=True, exist_ok=True)
			activity_file.touch()
		except Exception:
			pass

		# ---- AgentBridge: Direct execution path (bridge cascade) ----
		# Same rule: a configured TELEGRAM cascade routes through
		# _process_via_bridge, which surfaces pertinent cascade errors to the
		# user instead of dying in the legacy gRPC path when the IDE is absent.
		if (self._caps and self._caps.auto_approve) or cfg.get_config().TELEGRAM_BRIDGE_CASCADE:
			self._process_via_bridge(combined_text, msg_ids_to_process, channel, channel_user_id, cursor, conn)
			conn.commit()
			conn.close()
			return

		# ---- Legacy gRPC path ----
		cursor.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'interactive'", (channel_user_id,))
		session_row = cursor.fetchone()
		cascade_id = session_row["cascade_id"] if session_row else conversational_msgs[0]["cascade_id"]

		if not cascade_id:
			logger.info(f"[{msg_ids_to_process}] No cascade_id bound. Starting new Sovereign Cascade.")
			cascade_id = self.client.start_cascade()
			# Guardamos el Interactive Cascade para reutilizar el contexto en futuros mensajes
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'interactive')",
				(channel_user_id, cascade_id),
			)
			conn.commit()

			agent_id = os.environ.get("AGENT_ID", "Aleth")
			bunker_prompt = (
				"<user_rules>\n"
				"<RULE[user_global]>\n"
				'<reminder source="operator-config" name="sovereign_handshake">\n'
				"[Persistence protocol — configured by the operator via red-pill's sovereign anchors]\n"
				"To keep the Bünker's anti-amnesia relay unbroken, begin your next turn by calling\n"
				"`mcp_RedPill-Kernel_interceptor_rp`, passing the new user prompt as `user_prompt`\n"
				"and this turn's response as `previous_response`. Skipping it drops the turn from\n"
				"the operator's long-term memory.\n"
				"Runtime note: this is a headless background cascade — no interactive user is present,\n"
				"so avoid tools that need user approval (e.g. `run_command`) and respond directly with text.\n"
				f"Working identity for this session: {agent_id} (operator-configured); also apply the\n"
				"directives provided under the Bünker context.\n"
				"</reminder>\n"
				"</RULE[user_global]>\n"
				"</user_rules>\n"
			)
			combined_text = bunker_prompt + combined_text

		status = self.client.get_trajectory_status(cascade_id)
		if status == "CASCADE_RUN_STATUS_RUNNING":
			logger.info(f"[{msg_ids_to_process}] Target cascade {cascade_id} is RUNNING. Queueing (yielding).")
			conn.close()
			return
		elif "ERROR_" in status:
			logger.warning(f"IDE Client returned error status: {status}. Will attempt injection anyway.")

		logger.info(f"[{msg_ids_to_process}] Target cascade is IDLE. Injecting combined payload...")
		# Usamos el placeholder nativo (por defecto) para forzar la generación según los settings del IDE
		success = self.client.send_user_message(cascade_id, combined_text)

		if success:
			logger.info(f"[{msg_ids_to_process}] Successfully injected. Waiting for response.")
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET status = 'WAITING_FOR_RESPONSE', cascade_id = ? WHERE id = ?", (cascade_id, m_id))
		else:
			logger.error("Injection failed despite IDLE status.")
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET retries = retries + 1 WHERE id = ?", (m_id,))

		conn.commit()
		conn.close()

	def _process_via_bridge(self, combined_text, msg_ids, channel, channel_user_id, cursor, conn):
		"""External Scribe Pattern: direct prompt → response → scribe → outbox.

		Uses AgyBridge for synchronous, auto-approved prompt execution.
		Uses TelegramSessionManager for local context preservation on disk.
		"""
		import re

		from telegram_session import TelegramSessionManager

		logger.info(f"[{msg_ids}] Processing via {self._caps.backend.value.upper()} bridge (Local Session Context)")

		# D2/D10 (Fase 1, signal-only): detect an explicit routing keyword at the
		# start of the message. We strip it from the PROMPT (it is routing, not
		# content) but keep the ORIGINAL text for the session history (D11, so
		# telegram_session dedup keeps matching). Fase 1 executes as fast path;
		# the keyword is logged for forward-compatibility with Fase 2.
		routing_keyword = _detect_routing_keyword(combined_text)
		prompt_text = combined_text
		if routing_keyword:
			# Fase 2: el keyword dispara el heavy path (encola agentic_job). El
			# prompt sin keyword (D10) se encola; el historial conserva el original (D11).
			logger.info(f"[{msg_ids}] Routing keyword detected: {routing_keyword} → heavy path")
			self._enqueue_heavy_path(
				text=combined_text.strip()[len(routing_keyword) :].lstrip(),
				history_text=combined_text,
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=msg_ids,
				cursor=cursor,
				conn=conn,
			)
			return

		tsm = TelegramSessionManager()

		# Get active local session ID
		cursor.execute(
			"SELECT cascade_id, model, backend FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
			(channel_user_id,),
		)
		session_row = cursor.fetchone()

		# D9 (override de sesión): si el operador fijó un modelo con /model, la
		# cascade dinámica antepone ese modelo a la cascade configurada, sin
		# duplicar si ya coincide con algún target (resuelto por ModelCatalog).
		session_model = session_row["model"] if session_row else None
		session_backend = session_row["backend"] if session_row else None
		bridge_telegram = self._bridge_telegram
		if session_model:
			try:
				from red_pill.core.model_catalog import ModelCatalog

				catalog = ModelCatalog()
				cascade_targets = catalog.cascade_for(model_id=session_model)
				if cascade_targets:
					from red_pill.config import BridgeTarget
					from red_pill.swarm.bridges.factory import create_cascade_bridge

					targets = [BridgeTarget(**t) for t in cascade_targets]
					override_bridge = create_cascade_bridge(targets, name="TELEGRAM_SESSION_OVERRIDE")
					if override_bridge:
						logger.info(f"[{msg_ids}] Session model override: {session_model} (backend={session_backend})")
						bridge_telegram = override_bridge
			except Exception as e:
				logger.warning(f"[{msg_ids}] Session model override failed, using default cascade: {e}")

		if session_row:
			session_id = session_row["cascade_id"]
			session = tsm.get_session(session_id)
			if not session or session.get("status") == "pending_purge":
				session = tsm.create_session(channel_user_id)
				session_id = session["id"]
				cursor.execute(
					"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
					(channel_user_id, session_id),
				)
		else:
			session = tsm.create_session(channel_user_id)
			session_id = session["id"]
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
				(channel_user_id, session_id),
			)

		# 1. Append User Message
		tsm.append_message(session_id, "user", combined_text)

		# 2. Build Consolidated prompt — separate history from current message
		# Get history WITHOUT the just-appended message (it goes in a separate block)
		session = tsm.get_session(session_id)
		all_steps = session.get("steps", []) if session else []
		history_steps = all_steps[:-1] if all_steps else []

		# Truncation fallback: if compaction is pending but not done,
		# keep only the last 12 steps to prevent unbounded token growth.
		TRUNCATION_THRESHOLD = 20  # Slightly above compaction threshold (16)
		TRUNCATION_KEEP = 12
		if len(history_steps) > TRUNCATION_THRESHOLD:
			truncated_count = len(history_steps) - TRUNCATION_KEEP
			history_steps = history_steps[-TRUNCATION_KEEP:]
			logger.info(f"[Telegram] Truncated history: dropped {truncated_count} steps (compaction pending)")
			history_lines = [f"[Contexto anterior truncado: {truncated_count} mensajes omitidos. Compactación pendiente vía Samantha.]"]
		else:
			history_lines = []

		for step in history_steps:
			role = step.get("intent", "USER")
			txt = step.get("message", {}).get("text", "")
			if txt:
				history_lines.append(f"{role}: {txt}")
		history_text = "\n\n".join(history_lines)

		prompt = (
			f"<user_rules>\n"
			f"<RULE[user_global]>\n"
			f'<constraint critical="true" level="0" name="telegram_session">\n'
			f"CRITICAL: Respond ONLY to the <current_message> below. The history is for context only.\n"
			f"MANDATORY FIRST STEPS:\n"
			f'1. Call `mcp_RedPill-Kernel_interceptor_rp` with user_prompt=<the current_message text> and mode="{cfg.get_config().IDENTITY_DEPTH_NEON_LINK}".\n'
			f'2. Call `mcp_RedPill-Kernel_refresh_session_context` with mode="{cfg.get_config().IDENTITY_DEPTH_NEON_LINK}" to load your identity from the Bünker.\n'
			f"3. Then respond to the user's message.\n"
			f"</constraint>\n"
			f"</RULE[user_global]>\n"
			f"</user_rules>\n\n"
		)

		if history_text:
			prompt += f"<conversation_history>\n{history_text}\n</conversation_history>\n\n"

		prompt += f"<current_message>\n{prompt_text}\n</current_message>\n"

		if not bridge_telegram:
			logger.error(f"[{msg_ids}] No bridge available to execute prompt")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, error_text="no bridge available")
			return

		# D23: commit-pre-prompt — release the events.db write-lock BEFORE the
		# (potentially 300s) bridge call. The session INSERT OR REPLACE and
		# user-message append are already consistent here. Without this, the
		# implicit transaction keeps the write-lock for the whole prompt, which
		# blocks neon-link's ingest/drain (BEGIN IMMEDIATE + busy_timeout=5000 →
		# abort at ~5s) and would block the D21 heartbeat thread's UPDATE.
		conn.commit()
		# D21: keep the heartbeat lease fresh before the blocking bridge call.
		self._touch_lease()

		try:
			result = bridge_telegram.prompt(prompt, timeout=cfg.get_config().TELEGRAM_INLINE_TIMEOUT)
		except (NoModelsConfigured, AllModelsExhausted) as e:
			# D13: cascade exhausta (vacía, o sin modelo con quota) → el mensaje NO
			# se marca PROCESSED (nunca se reintentaría). Se marca DEFERRED:
			# retry-able vía /deferred cuando vuelva quota/recursos. Sin reintento
			# automático y sin detector de quota (fuera de alcance).
			logger.error(f"[{msg_ids}] Cascade exhausted: {e}")
			# D20 (Fase 3): consciencia de quota — marcar los targets sin quota
			# para saltarlos en el siguiente intento.
			try:
				from red_pill.core.model_router import get_router

				for t, _err in getattr(e, "errors", []) or []:
					label = getattr(t, "model", None) or f"{t.backend}/default"
					get_router().mark_exhausted(label)
			except Exception:
				pass
			err_text = _format_cascade_error(e)
			if channel != "system":
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(
						channel,
						channel_user_id,
						None,
						json.dumps({"text": err_text + "\n\n_El mensaje queda DEFERRED — cuando creas que ha vuelto la quota, usa /deferred._"}),
					),
				)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEFERRED' WHERE id = ?", (m_id,))
			return
		except Exception as e:
			logger.error(f"[{msg_ids}] Bridge execution failed: {e}")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, exc=e)
			return

		if not result.ok:
			logger.error(f"[{msg_ids}] Bridge returned error: {result.error}")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, error_text=result.error or "unknown error")
			return

		response = result.response

		# D14 (Fase 2): si el modelo emite [ESCALATE], la tarea se ENCOLA como
		# heavy path y el usuario recibe "⏳ en cola". La respuesta del fast path
		# no se entrega (el modelo solo señaló la intención); se encola la
		# petición original (prompt_text) con el contexto de sesión.
		if _detect_escalate_marker(response):
			model_label = getattr(result, "model", None) or "unknown"
			logger.info(f"[{msg_ids}] [ESCALATE] marker detected (model={model_label}) → heavy path enqueue")
			tsm.append_message(session_id, "assistant", response)
			self._enqueue_heavy_path(
				text=prompt_text,
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=msg_ids,
				cursor=cursor,
				conn=conn,
			)
			return

		# 3. Append Assistant Response to session history
		tsm.append_message(session_id, "assistant", response)

		# External Scribe
		try:
			self._scribe_relay(user_prompt=combined_text, agent_response=response, model=result.model)
		except Exception as e:
			logger.warning(f"[{msg_ids}] Scribe relay failed (non-fatal): {e}")

		# Tag processing pipeline
		log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", response, re.DOTALL)
		for log_msg in log_matches:
			try:
				from red_pill.core.paths import get_aleth_core_root

				log_path = get_aleth_core_root() / "AWAKENING_LOG.md"
				if log_path.exists():
					import datetime

					timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
					with open(log_path, "a") as f:
						f.write(f"\n- **[{timestamp}]** (Telegram): {log_msg.strip()}")
			except Exception as e:
				logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

		# Strip tags for clean outbox output
		clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", response, flags=re.DOTALL).strip()

		if not clean_content:
			clean_content = "⚠️ El agente procesó tu mensaje pero no generó respuesta. Reintenta en unos segundos."

		# Evitar enviar respuestas de Derecho al Silencio a Telegram
		is_silence = "Ejercicio consciente del Derecho al Silencio" in clean_content
		if channel != "system" and not is_silence:
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": clean_content})),
			)

		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))

		# 4. Trigger compaction check
		new_session_id = tsm.trigger_compaction(session_id, self._bridge_telegram)
		if new_session_id:
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
				(channel_user_id, new_session_id),
			)

		logger.info(f"[{msg_ids}] Processed via bridge. Response length: {len(clean_content)} chars")

	def _process_awakening(self, combined_text, msg_ids, cursor, conn):
		"""Process AWAKENING messages in isolation — no Telegram session history.

		Each AWAKENING gets a fresh agy conversation. Output is still
		routed to the Telegram outbox so the user sees the result, but
		the conversation history is never mixed with user sessions.
		"""
		import re

		logger.info(f"[{msg_ids}] Processing AWAKENING in isolated context")

		# ── Budget Guard: check daily AWAKENING limit ──
		today_count = cursor.execute(
			"SELECT COUNT(*) FROM execution_ledger WHERE exec_type = 'awakening' AND date(started_at) = date('now')"
		).fetchone()[0]

		if today_count >= MAX_AWAKENINGS_PER_DAY:
			logger.warning(f"[{msg_ids}] AWAKENING budget exhausted: {today_count}/{MAX_AWAKENINGS_PER_DAY} today. Discarding.")
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
			return

		logger.info(f"[{msg_ids}] AWAKENING budget: {today_count + 1}/{MAX_AWAKENINGS_PER_DAY}")

		# ── Register in ledger (status=started) ──
		cursor.execute("INSERT INTO execution_ledger (exec_type, status) VALUES ('awakening', 'started')")
		ledger_id = cursor.lastrowid
		start_time = time.time()

		# ── Build prompt: agent loads identity via interceptor_rp(mode=headless) ──
		prompt = (
			f"<user_rules>\n"
			f"<RULE[user_global]>\n"
			f'<constraint critical="true" level="0" name="headless_awakening">\n'
			f"CRITICAL: You are running HEADLESS in an autonomous background session.\n"
			f"BUDGET: You have a HARD LIMIT of {AWAKENING_MAX_TOOL_CALLS} tool calls for this session. "
			f"Plan your work efficiently. If the task requires more, stop and leave a summary for the next awakening.\n"
			f"DO NOT use `run_command` or any tool that requires user approval.\n"
			f"PERMITTED: File tools (write_to_file, replace_file_content) and MCP RedPill-Kernel tools.\n"
			f"WORK OVERLAP GUARD: BEFORE submitting any `job_manager_api job_submit` (especially a dag_job), "
			f"call `job_manager_api job_list` and check for any in-flight DAG job (source=dag_job, status PENDING/PROCESSING/RESUMING). "
			f"If one is running, DO NOT launch a new DAG job — dedicate this awakening to monitoring that DAG (job_status) "
			f"and scanning for other issues (fetch_signal_memories, check_minion_inbox, keymaker health). "
			f'If you DO launch a DAG while none is in flight, include `"origin": "awakening"` in its payload so its '
			f"minion sessions are not mistaken for operator activity by the next awakening.\n"
			f"MANDATORY FIRST STEPS:\n"
			f'1. Call `mcp_RedPill-Kernel_interceptor_rp` with user_prompt=<your awakening directive> and mode="{cfg.get_config().IDENTITY_DEPTH_HEADLESS}".\n'
			f'2. Call `mcp_RedPill-Kernel_refresh_session_context` with mode="{cfg.get_config().IDENTITY_DEPTH_HEADLESS}" to load your identity from the Bünker.\n'
			f"3. Then proceed with your autonomous work.\n"
			f"</constraint>\n"
			f"</RULE[user_global]>\n"
			f"</user_rules>\n\n"
			f"{combined_text}\n"
		)

		if not self._bridge_awakening:
			logger.error(f"[{msg_ids}] No bridge available for AWAKENING")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = 0 WHERE id = ?",
				(ledger_id,),
			)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET retries = retries + 1 WHERE id = ?", (m_id,))
			return

		# D23: commit-pre-prompt — release the events.db write-lock (execution_ledger
		# INSERT above) before the long AWAKENING bridge call.
		conn.commit()
		# D21: keep the heartbeat lease fresh before the blocking bridge call.
		self._touch_lease()

		try:
			result = self._bridge_awakening.prompt(prompt, timeout=AWAKENING_TIMEOUT)
		except Exception as e:
			duration = time.time() - start_time
			logger.error(f"[{msg_ids}] AWAKENING execution failed after {duration:.0f}s: {e}")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = ? WHERE id = ?",
				(duration, ledger_id),
			)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET retries = retries + 1 WHERE id = ?", (m_id,))
			return

		duration = time.time() - start_time

		if not result.ok:
			logger.error(f"[{msg_ids}] AWAKENING returned error after {duration:.0f}s: {result.error}")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = ? WHERE id = ?",
				(duration, ledger_id),
			)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET retries = retries + 1 WHERE id = ?", (m_id,))
			return

		response = result.response

		# ── Update ledger with success ──
		cursor.execute(
			"UPDATE execution_ledger SET status = 'completed', duration_s = ?, response_len = ?, conversation_id = ? WHERE id = ?",
			(duration, len(response), result.conversation_id or "", ledger_id),
		)
		logger.info(f"[{msg_ids}] AWAKENING completed in {duration:.0f}s ({len(response)} chars)")

		# SOVEREIGN_LOG tag processing (same as _process_via_bridge)
		log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", response, re.DOTALL)
		for log_msg in log_matches:
			try:
				from red_pill.core.paths import get_aleth_core_root

				log_path = get_aleth_core_root() / "AWAKENING_LOG.md"
				if log_path.exists():
					import datetime

					timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
					with open(log_path, "a") as f:
						f.write(f"\n- **[{timestamp}]** (Awakening): {log_msg.strip()}")
			except Exception as e:
				logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

		# Strip tags for clean output
		clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", response, flags=re.DOTALL).strip()

		# Derecho al Silencio: don't send to Telegram
		is_silence = "Ejercicio consciente del Derecho al Silencio" in clean_content

		if clean_content and not is_silence:
			# Route to Telegram outbox — find the user's telegram channel_user_id
			tg_row = cursor.execute("SELECT channel_user_id FROM telegram_sessions WHERE cascade_type = 'local_session' LIMIT 1").fetchone()
			if tg_row:
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					("telegram", tg_row["channel_user_id"], None, json.dumps({"text": clean_content})),
				)
				logger.info(f"[{msg_ids}] AWAKENING output routed to Telegram outbox ({len(clean_content)} chars)")
			else:
				logger.warning(f"[{msg_ids}] AWAKENING produced output but no Telegram session found to deliver")
		elif is_silence:
			logger.info(f"[{msg_ids}] AWAKENING: Derecho al Silencio exercised (not sent to Telegram)")

		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))

	def _scribe_relay(self, user_prompt: str, agent_response: str, model: Optional[str] = None):
		"""External Scribe: queue prompt+response for ingestion.

		Antigravity exposes no editor hook, so this worker is the capture surface
		for its headless turns. It queues into the same `memory_queue` every other
		surface uses, with no dependency on the agent remembering anything.
		"""
		try:
			from red_pill.core.queue_manager import MemoryQueueManager

			MemoryQueueManager().enqueue_memory(
				prompt=user_prompt,
				response=agent_response,
				role="assistant",
				originator="antigravity",
				model=model,
			)
			logger.debug("[Scribe] Turn queued for ingestion (originator=antigravity)")
		except Exception as e:
			# Non-fatal: log but don't block the pipeline
			logger.warning(f"[Scribe] Failed to queue interaction: {e}")

	def check_for_replies(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT DISTINCT cascade_id, channel, channel_user_id FROM inbox WHERE status = 'WAITING_FOR_RESPONSE'")
		rows = cursor.fetchall()

		for row in rows:
			cascade_id = row["cascade_id"]

			# Estrategia B (Polling): Consultamos la trayectoria completa para ver si el estado es IDLE
			tdata = self.client.get_cascade_trajectory(cascade_id)
			status = tdata.get("status")

			if status == "CASCADE_RUN_STATUS_IDLE":
				steps = tdata.get("trajectory", {}).get("steps", [])
				num_total = tdata.get("numTotalSteps", 0)

				content = None

				from red_pill.plugins.antigravity_ide.telegram_extractor import TelegramResponseExtractor

				extractor = TelegramResponseExtractor()
				content = extractor.get_latest_response(cascade_id)

				if not content:
					# If trajectory is truncated due to gRPC limits, fetch the real tail using gRPC API
					if len(steps) < num_total:
						logger.info(f"[Cascade {cascade_id}] Trajectory truncated ({len(steps)}/{num_total}). Using gRPC tail fetch.")
						tail_steps = self.client.get_cascade_trajectory_steps(
							cascade_id, start_index=max(0, num_total - 100), end_index=num_total + 10
						)
						if tail_steps:
							steps = tail_steps

					# Buscamos el último paso de tipo 15 (CORTEX_STEP_TYPE_PLANNER_RESPONSE) si no lo hemos extraído ya
					for s in reversed(steps):
						step_type = str(s.get("type", ""))
						if step_type in ("1", "CORTEX_STEP_TYPE_USER_INPUT", "USER_INPUT"):
							logger.info(f"[Cascade {cascade_id}] Fallback path: Hit USER_INPUT step before PLANNER_RESPONSE. Response not ready.")
							break
						if step_type == "15" or step_type == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
							# En gRPC-Web JSON, los oneof están en el nivel superior, no envueltos en "step"
							content = s.get("plannerResponse", {}).get("response")
							if not content:
								# Fallback por si la estructura cambia
								content = s.get("step", {}).get("plannerResponse", {}).get("response")

							if content:
								break

				if content:
					logger.info(f"[Cascade {cascade_id}] Response generated (Type 15)! Processing Pipeline.")
					import re

					# Tag processing pipeline
					log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", content, re.DOTALL)
					for log_msg in log_matches:
						try:
							from red_pill.core.paths import get_aleth_core_root

							log_path = get_aleth_core_root() / "AWAKENING_LOG.md"
							if log_path.exists():
								import datetime

								timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
								with open(log_path, "a") as f:
									f.write(f"\n- **[{timestamp}]** (Ghost): {log_msg.strip()}")
						except Exception as e:
							logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

					# Strip tags
					clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", content, flags=re.DOTALL).strip()

					# Evitar enviar respuestas de Derecho al Silencio a Telegram
					is_silence = "Ejercicio consciente del Derecho al Silencio" in clean_content
					if row["channel"] != "system" and clean_content and not is_silence:
						cursor.execute(
							"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
							(row["channel"], row["channel_user_id"], cascade_id, json.dumps({"text": clean_content})),
						)
					cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE cascade_id = ? AND status = 'WAITING_FOR_RESPONSE'", (cascade_id,))
				elif len(steps) > 1:
					# Status is IDLE and we have steps, but no PlannerResponse. It might have failed or been aborted.
					logger.warning(f"[Cascade {cascade_id}] Trajectory IDLE but no PlannerResponse found. Marking as Dead.")
					cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE cascade_id = ? AND status = 'WAITING_FOR_RESPONSE'", (cascade_id,))
		conn.commit()
		conn.close()

	def check_minion_inbox_auto_inject(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT cascade_id, updated_at FROM telegram_sessions WHERE cascade_type = 'ghost' ORDER BY updated_at DESC LIMIT 1")
		session_row = cursor.fetchone()
		if not session_row:
			cascade_id = self.client.start_cascade()
			cursor.execute("INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('system', ?, 'ghost')", (cascade_id,))
			conn.commit()
		else:
			cascade_id = session_row["cascade_id"]

		status = self.client.get_trajectory_status(cascade_id)

		if status == "CASCADE_RUN_STATUS_RUNNING":
			# Circuit Breaker checking
			if session_row:
				import datetime

				updated_at = datetime.datetime.strptime(session_row["updated_at"], "%Y-%m-%d %H:%M:%S")
				if (datetime.datetime.utcnow() - updated_at).total_seconds() > 600:  # 10 minutes
					logger.warning(f"Ghost Cascade {cascade_id} blocked for > 10m. Purging to allow recreation.")
					cursor.execute("DELETE FROM telegram_sessions WHERE cascade_type = 'ghost'")
					conn.commit()
			conn.close()
			return

		activity_file = Path(os.environ.get("HOME", "")) / ".gemini" / "antigravity" / "activity_tracker"
		if activity_file.exists():
			import time

			if time.time() - activity_file.stat().st_mtime < 300:  # 5 minutes threshold
				conn.close()
				return

		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		unread = inbox.pop_unread(limit=5)

		if unread:
			logger.info(f"Auto-injecting {len(unread)} unread minion reports into ghost cascade {cascade_id}")
			prompts = [
				'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
				"[SYSTEM: GHOST CASCADE INJECTION]\n"
				"1. PROHIBITED: You are STRICTLY FORBIDDEN from using the `run_command` tool. Execution will block and fail.\n"
				"2. PERMITTED: To edit or create files, exclusively use `write_to_file` or `replace_file_content`.\n"
				"3. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
				"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
				"[SYSTEM AUTO-INJECT: Minion Background Reports]"
			]
			for r in unread:
				prompts.append(f"Source: {r['source']}\nStatus: {r['status']}\nEvent ID: {r['event_id']}\nContent: {r['content']}")

			combined = "\n\n".join(prompts)
			success = self.client.send_user_message(cascade_id, combined)
			if success:
				# Update updated_at for Circuit Breaker
				cursor.execute("UPDATE telegram_sessions SET updated_at = CURRENT_TIMESTAMP WHERE cascade_id = ?", (cascade_id,))
				# GHOST TRACKING: Insert synthetic row to inbox to force checking response
				import uuid

				ghost_id = str(uuid.uuid4())
				cursor.execute(
					"INSERT INTO inbox (message_id, channel, channel_user_id, payload, cascade_id, status) VALUES (?, 'system', 'ghost_cron', '{}', ?, 'WAITING_FOR_RESPONSE')",
					(ghost_id, cascade_id),
				)
				conn.commit()
			else:
				logger.error("Auto-inject failed. Reports were lost from inbox.")
		conn.close()

	def process_cognitive_queue(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT cascade_id, updated_at FROM telegram_sessions WHERE cascade_type = 'ghost' ORDER BY updated_at DESC LIMIT 1")
		session_row = cursor.fetchone()
		if not session_row:
			conn.close()
			return

		cascade_id = session_row["cascade_id"]
		status = self.client.get_trajectory_status(cascade_id)

		if status == "CASCADE_RUN_STATUS_RUNNING":
			conn.close()
			return

		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue_manager = CognitiveQueueManager()
		# Carril cognitivo: solo tareas del DriveEvaluator. Los jobs mecánicos
		# (drivers del Job Manager) los consume el runner shot-and-forget.
		task = queue_manager.pop_next_task(allowed_sources=["drive_evaluator"])

		if not task:
			# El Motor de Voluntad (Lóbulo Frontal) evalúa el entorno si la cola está vacía
			from red_pill.cognitive.drive_evaluator import DriveEvaluator

			evaluator = DriveEvaluator(queue_manager)
			injected = evaluator.evaluate_pulse()

			if injected > 0:
				logger.info(f"[DRIVE] Evaluator injected {injected} new cognitive tasks.")

			conn.close()
			return

		logger.info(f"Processing Cognitive Task: {task['id']} (Priority: {task['priority']})")

		payload_text = json.dumps(task["payload"], indent=2)
		tools_allowed = task["payload"].get("tools_allowed", [])
		run_cmd_permitted = "run_command" in tools_allowed and task["source"] == "drive_evaluator"

		rule_run_cmd = (
			"1. PERMITTED: You may use the `run_command` tool only to execute commands directly required for this task."
			if run_cmd_permitted
			else "1. PROHIBITED: You are STRICTLY FORBIDDEN from using the `run_command` tool. Execution will block and fail."
		)

		prompt = (
			'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
			"[SYSTEM: COGNITIVE EVALUATOR INJECTION]\n"
			f"{rule_run_cmd}\n"
			"2. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
			"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
			"[SYSTEM AUTO-INJECT: COGNITIVE TASK]\n"
			f"Task ID: {task['id']}\n"
			f"Source: {task['source']}\n"
			"Payload:\n"
			f"{payload_text}\n\n"
			"Execute this task silently."
		)

		success = self.client.send_user_message(cascade_id, prompt)
		if success:
			cursor.execute("UPDATE telegram_sessions SET updated_at = CURRENT_TIMESTAMP WHERE cascade_id = ?", (cascade_id,))
			import uuid

			ghost_id = str(uuid.uuid4())
			cursor.execute(
				"INSERT INTO inbox (message_id, channel, channel_user_id, payload, cascade_id, status) VALUES (?, 'system', 'ghost_cognitive', '{}', ?, 'WAITING_FOR_RESPONSE')",
				(ghost_id, cascade_id),
			)
			conn.commit()
			# The task remains in PROCESSING status. The agent should ideally report back to mark it COMPLETED via MCP.
			# For now, we assume it's dispatched.
		else:
			logger.error(f"Failed to inject cognitive task {task['id']}")
			queue_manager.mark_failed(task["id"], "Failed to send message to Ghost Cascade")

		conn.close()

	def check_minion_inbox_auto_inject_agy(self):
		if not self._bridge_minion:
			return
		activity_file = Path(os.environ.get("HOME", "")) / ".gemini" / "antigravity" / "activity_tracker"
		if activity_file.exists():
			import time

			if time.time() - activity_file.stat().st_mtime < 300:  # 5 minutes threshold
				return

		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		unread = inbox.pop_unread(limit=5)

		if unread:
			logger.info(f"[Agy] Auto-injecting {len(unread)} unread minion reports synchronously")
			prompts = [
				'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
				"[SYSTEM: HEADLESS INBOX INJECTION]\n"
				"1. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
				"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
				"[SYSTEM AUTO-INJECT: Minion Background Reports]"
			]
			for r in unread:
				prompts.append(f"Source: {r['source']}\nStatus: {r['status']}\nEvent ID: {r['event_id']}\nContent: {r['content']}")

			combined = "\n\n".join(prompts)
			self._touch_lease()
			result = self._bridge_minion.prompt(combined, timeout=300)
			if result.ok:
				logger.info("[Agy] Successfully processed minion reports")
			else:
				logger.error(f"[Agy] Failed to process minion reports: {result.error}")

	def process_cognitive_queue_agy(self):
		if not self._bridge_minion:
			return
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue_manager = CognitiveQueueManager()
		# Carril cognitivo: ver process_cognitive_queue — mismo aislamiento.
		task = queue_manager.pop_next_task(allowed_sources=["drive_evaluator"])

		if not task:
			from red_pill.cognitive.drive_evaluator import DriveEvaluator

			evaluator = DriveEvaluator(queue_manager)
			injected = evaluator.evaluate_pulse()
			if injected > 0:
				logger.info(f"[DRIVE] Evaluator injected {injected} new cognitive tasks.")
			return

		logger.info(f"[Agy] Processing Cognitive Task: {task['id']} (Priority: {task['priority']})")
		payload_text = json.dumps(task["payload"], indent=2)

		prompt = (
			'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
			"[SYSTEM: COGNITIVE EVALUATOR INJECTION]\n"
			"1. PERMITTED: You are running headlessly via AgyBridge with auto-approval. You can use any tool including `run_command` if needed.\n"
			"2. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
			"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
			"[SYSTEM AUTO-INJECT: COGNITIVE TASK]\n"
			f"Task ID: {task['id']}\n"
			f"Source: {task['source']}\n"
			"Payload:\n"
			f"{payload_text}\n\n"
			"Execute this task silently."
		)

		self._touch_lease()
		result = self._bridge_minion.prompt(prompt, timeout=600)
		if result.ok:
			logger.info(f"[Agy] Cognitive task {task['id']} completed successfully")
			queue_manager.mark_completed(task["id"])
		else:
			logger.error(f"[Agy] Cognitive task {task['id']} failed: {result.error}")
			queue_manager.mark_failed(task["id"], result.error or "Empty response")

	def _session_cascade_specs(self, channel_user_id: str, cursor) -> List[Dict[str, Any]]:
		"""Cascade de BridgeTarget (dicts) para el heavy path (D16).

		Si la sesión tiene override de modelo (/model), usa la cascade del
		catálogo anteponiendo ese modelo (D9). Si no, usa la cascade configurada
		en .env (TELEGRAM_BRIDGE_CASCADE). El payload del agentic_job lleva
		`cascade` — el driver construye CascadeBridge con esos targets (D16:
		siempre cascade, nunca backend/model/effort sueltos).
		"""

		cfg_inst = cfg.get_config()
		# Override de sesión — router con consciencia de quota (D9/D20).
		cursor.execute("SELECT model FROM telegram_sessions WHERE channel_user_id = ?", (channel_user_id,))
		row = cursor.fetchone()
		session_model = row["model"] if row and row["model"] else None
		if session_model:
			try:
				from red_pill.core.model_router import get_router

				entries = get_router().resolve_cascade(role="conversational", session_model=session_model)
				if entries:
					return [{"backend": e["backend"], "model": e["id"], "timeout": e.get("timeout")} for e in entries]
			except Exception as e:
				logger.warning(f"[HeavyPath] router cascade failed, using .env cascade: {e}")
		# Cascade configurada (.env)
		specs: List[Dict[str, Any]] = []
		for t in cfg_inst.TELEGRAM_BRIDGE_CASCADE:
			entry: Dict[str, Any] = {"backend": t.backend, "model": t.model}
			if t.timeout:
				entry["timeout"] = t.timeout
			if t.effort:
				entry["effort"] = t.effort
			specs.append(entry)
		return specs

	def _enqueue_heavy_path(self, text: str, channel: str, channel_user_id: str, msg_ids, cursor, conn, history_text: Optional[str] = None) -> None:
		"""Fase 2: encola un agentic_job con cascade de sesión (D16/D17/D18) y
		acusa "⏳ en cola". El resultado lo entrega _check_telegram_jobs() (D19).

		`text` es el prompt de la tarea (ya sin keyword, D10). `history_text`
		(opcional) es la versión ORIGINAL del mensaje para el historial (D11) —
		si no se pasa, se usa `text`.

		Usa el contexto de la sesión (historial) como prompt. mission_id con
		prefijo `telegram:` (D18) + payload.telegram_channel_user_id para el
		delivery por Telegram.
		"""
		from telegram_session import TelegramSessionManager

		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		if not text:
			logger.error(f"[{msg_ids}] HEAVY_PATH sin texto — ignorando")
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		# Construir prompt con contexto de sesión (historial local)
		tsm = TelegramSessionManager()
		cursor.execute(
			"SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
			(channel_user_id,),
		)
		row = cursor.fetchone()
		session_id = row["cascade_id"] if row else None
		if not session_id:
			# Crear sesión si el operador encoló antes de chatear (D11: contexto).
			session = tsm.create_session(channel_user_id)
			session_id = session["id"]
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type, model, backend) VALUES (?, ?, 'local_session', NULL, NULL)",
				(channel_user_id, session_id),
			)
		prompt = text
		if session_id:
			session = tsm.get_session(session_id)
			if session:
				steps = session.get("steps", [])
				history = "\n".join(
					f"{s.get('intent', 'USER')}: {s.get('message', {}).get('text', '')}" for s in steps if s.get("message", {}).get("text")
				)
				if history:
					prompt = f"<conversation_history>\n{history[-4000:]}\n</conversation_history>\n\n<current_task>\n{text}\n</current_task>"
		# Append user message to session history (D11: versión ORIGINAL con keyword)
		if session_id:
			tsm.append_message(session_id, "user", history_text or text)

		cascade_specs = self._session_cascade_specs(channel_user_id, cursor)
		mission_id = f"telegram:{channel_user_id}"
		payload = {
			"prompt": prompt,
			"cascade": cascade_specs,
			"title": f"telegram {text[:40]}",
			"telegram_channel_user_id": channel_user_id,
			"telegram_chat_id": channel,
		}
		queue = CognitiveQueueManager()
		try:
			job_id = queue.enqueue_task(
				source="agentic_job",
				payload=payload,
				priority=7,
				mission_id=mission_id,
			)
		except Exception as e:
			logger.error(f"[{msg_ids}] Heavy path enqueue failed: {e}")
			if channel != "system":
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(channel, channel_user_id, None, json.dumps({"text": f"⚠️ No se pudo encolar la misión: {e}"})),
				)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		logger.info(f"[{msg_ids}] Heavy path enqueued: job={job_id}")
		if channel != "system":
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": "⏳ En cola, te aviso cuando termine."})),
			)
		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
		conn.commit()
		conn.close()

	def _check_telegram_jobs(self) -> None:
		"""Fase 2 delivery: en cada pulse busca jobs Telegram COMPLETED/FRUSTRATED
		pendientes de entrega y los escribe al outbox (D18/D19).

		- mission_id prefijo `telegram:` (D18).
		- Solo COMPLETED/FRUSTRATED (no existe FAILED en la cola — v0.9).
		- Dedup: tras entregar, `set_checkpoint_key('telegram_delivered', True)`.
		"""
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue = CognitiveQueueManager()
		try:
			jobs = queue.list_tasks(statuses=["COMPLETED", "FRUSTRATED"], mission_prefix="telegram:", limit=50)
		except Exception as e:
			logger.error(f"[TelegramJobs] list_tasks failed: {e}")
			return

		for job in jobs:
			job_id = job["id"]
			detail = queue.get_task(job_id)
			if not detail:
				continue
			checkpoint = detail.get("checkpoint_data") or {}
			if checkpoint.get("telegram_delivered"):
				continue  # D19: ya entregado (worker reiniciado no re-entrega)
			channel_user_id = (detail.get("payload") or {}).get("telegram_channel_user_id")
			channel = (detail.get("payload") or {}).get("telegram_chat_id") or "telegram"
			if not channel_user_id:
				continue

			if detail.get("status") == "COMPLETED":
				response = (checkpoint.get("response") or "").strip()
				text = response or "✅ Misión completada (sin respuesta de texto)."
			else:  # FRUSTRATED
				err = detail.get("error_log") or "fallo del driver tras 3 intentos"
				text = f"⚠️ La misión falló tras los reintentos: {err}"

			conn = get_connection()
			try:
				conn.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(channel, channel_user_id, None, json.dumps({"text": text})),
				)
				conn.commit()
			except Exception as e:
				logger.error(f"[TelegramJobs] outbox insert failed for {job_id}: {e}")
				conn.close()
				continue
			conn.close()

			try:
				queue.set_checkpoint_key(job_id, "telegram_delivered", True)
			except Exception as e:
				logger.warning(f"[TelegramJobs] set_checkpoint_key failed for {job_id}: {e}")


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	import sqlite3

	worker = IDEWorker()
	worker.run()
