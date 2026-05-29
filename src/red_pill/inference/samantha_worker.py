"""
SamanthaWorker — Event-driven background thread for local LLM task processing.

Architecture:
- Daemon thread of the IDEWorker (dies with parent, NOT a separate daemon)
- Sleeps via threading.Event.wait() (0 CPU when idle)
- Wakes on signal from worker when tasks are pending
- Processes ALL pending tasks in batch (single Samantha boot)
- Grace period before shutdown to avoid boot-churn
- Watchdog: worker monitors thread health, restarts if stuck

This replaces the synchronous drain_queue() that blocked the worker poll loop.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────
SAMANTHA_SOURCE = "samantha"
WATCHDOG_TIMEOUT = 120  # seconds — if no heartbeat for this long, worker kills us
DEFAULT_IDLE_TIMEOUT = 60  # seconds — grace period before shutting down ephemeral


# ── Task handlers registry ────────────────────────────────
_HANDLERS: Dict[str, Callable] = {}


def register_handler(action: str):
	"""Decorator to register a Samantha task handler."""

	def decorator(fn):
		_HANDLERS[action] = fn
		return fn

	return decorator


# ── Built-in handlers ─────────────────────────────────────


@register_handler("compact_session")
def _handle_compact_session(payload: Dict[str, Any], samantha_fn: Callable) -> Dict[str, Any]:
	"""Compacts a Telegram session using Samantha for summarization."""
	history_text = payload.get("history_text", "")

	if not history_text:
		return {"status": "skipped", "reason": "empty history"}

	summary = samantha_fn(
		prompt=(
			"Resume la siguiente conversación de Telegram entre el operador (Joan) y el agente (Aleth). "
			"Crea un resumen técnico y de progreso conciso para usarlo como contexto en el siguiente turno. "
			"Sé directo y resume los puntos clave de decisión y tareas pendientes.\n\n"
			f"{history_text}"
		),
		system_prompt=(
			"You are a conversation summarizer. Output ONLY the summary. "
			"Be concise, technical, and include key decisions and pending tasks. "
			"Do not add conversational filler."
		),
		max_tokens=300,
	)

	if not summary:
		return {"status": "error", "reason": "Samantha returned empty"}

	return {"status": "completed", "summary": summary, "session_id": payload.get("session_id", "")}


@register_handler("classify")
def _handle_classify(payload: Dict[str, Any], samantha_fn: Callable) -> Dict[str, Any]:
	"""Classify text into categories using Samantha."""
	text = payload.get("text", "")
	categories = payload.get("categories", [])

	result = samantha_fn(
		prompt=f"Classify the following text into one of these categories: {', '.join(categories)}.\n\nText: {text}\n\nOutput ONLY the category name.",
		system_prompt="You are a classifier. Output ONLY the category name, nothing else.",
		max_tokens=20,
	)

	return {"status": "completed", "category": result or "unknown"}


@register_handler("summarize")
def _handle_summarize(payload: Dict[str, Any], samantha_fn: Callable) -> Dict[str, Any]:
	"""Generic summarization task."""
	text = payload.get("text", "")
	max_tokens = payload.get("max_tokens", 200)

	result = samantha_fn(
		prompt=f"Summarize the following text concisely:\n\n{text}",
		system_prompt="You are a summarizer. Be concise and direct. Output ONLY the summary.",
		max_tokens=max_tokens,
	)

	return {"status": "completed", "summary": result or ""}


# ── Enqueue helper (used by producers) ────────────────────


def enqueue(action: str, payload: Dict[str, Any], priority: int = 5) -> str:
	"""Enqueue a task for Samantha processing.

	Args:
		action: Handler name (e.g. 'compact_session', 'classify', 'summarize')
		payload: Task-specific data
		priority: 1-10, higher = more urgent

	Returns:
		Task ID
	"""
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	payload["action"] = action
	qm = CognitiveQueueManager()
	task_id = qm.enqueue_task(source=SAMANTHA_SOURCE, payload=payload, priority=priority)
	logger.info(f"[SamanthaQueue] Enqueued task {task_id}: {action}")
	return task_id


# ── SamanthaWorker Thread ─────────────────────────────────


class SamanthaWorker(threading.Thread):
	"""
	Event-driven daemon thread for processing Samantha (local LLM) tasks.

	Lifecycle:
	1. Sleeps via Event.wait() → 0 CPU
	2. Worker signals wake() → thread wakes
	3. Boots Samantha (on-demand or via Hypervisor)
	4. Drains ALL pending tasks in batch
	5. Grace period (IDLE_TIMEOUT) → if new work arrives, continue
	6. Shutdown Samantha if ephemeral
	7. Back to sleep
	"""

	daemon = True  # Dies with the worker process

	def __init__(self, idle_timeout: int = DEFAULT_IDLE_TIMEOUT):
		super().__init__(name="SamanthaWorker")
		self._wake_event = threading.Event()
		self._running = True
		self._idle_timeout = idle_timeout
		self._health_ts = time.time()
		self._current_task_id: Optional[str] = None
		self._ephemeral_proc: Optional[Any] = None  # Track ephemeral process for watchdog kill
		self._stats = {"processed": 0, "failed": 0, "boots": 0}

	def wake(self) -> None:
		"""NON-BLOCKING. Signal that there are pending tasks."""
		self._wake_event.set()

	def is_healthy(self, timeout: int = WATCHDOG_TIMEOUT) -> bool:
		"""Watchdog check: has the thread reported health recently?"""
		return (time.time() - self._health_ts) < timeout

	def get_stats(self) -> Dict[str, Any]:
		"""Return processing statistics."""
		return {**self._stats, "healthy": self.is_healthy(), "alive": self.is_alive()}

	def stop(self) -> None:
		"""Graceful shutdown."""
		self._running = False
		self._wake_event.set()  # Unblock wait

	def force_kill_ephemeral(self) -> None:
		"""Emergency: kill the ephemeral llama-server process (called by watchdog)."""
		if self._ephemeral_proc:
			try:
				self._ephemeral_proc.terminate()
				self._ephemeral_proc.wait(timeout=5)
				logger.warning("[SamanthaWorker] Watchdog killed ephemeral process")
			except Exception as e:
				logger.error(f"[SamanthaWorker] Failed to kill ephemeral: {e}")
				try:
					self._ephemeral_proc.kill()
				except Exception:
					pass
			self._ephemeral_proc = None

	def run(self) -> None:
		"""Main thread loop."""
		logger.info("[SamanthaWorker] Thread started (event-driven, 0 CPU when idle)")
		while self._running:
			try:
				self._wake_event.wait()  # ← SLEEP (0 CPU)
				if not self._running:
					break
				self._wake_event.clear()
				self._health_ts = time.time()
				self._drain_cycle()
			except Exception as e:
				logger.error(f"[SamanthaWorker] Cycle error: {e}")
				time.sleep(5)  # Back-off before retrying

		logger.info(f"[SamanthaWorker] Thread stopped. Stats: {self._stats}")

	def _drain_cycle(self) -> None:
		"""Boot Samantha, drain all tasks, shutdown if ephemeral."""
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		qm = CognitiveQueueManager()

		# Peek first — if no work, don't boot
		if not qm.has_pending(source=SAMANTHA_SOURCE):
			return

		# Boot Samantha
		port = self._boot_samantha()
		if not port:
			self._fail_all_pending(qm, "Samantha boot failed")
			return

		try:
			# Drain loop
			while self._running:
				task = qm.pop_next_task(allowed_sources=[SAMANTHA_SOURCE])
				if not task:
					break

				self._current_task_id = task["id"]
				self._health_ts = time.time()
				self._process_task(qm, task, port)
				self._current_task_id = None

			# Grace period: wait for new work before killing ephemeral
			if self._ephemeral_proc and self._running:
				logger.debug(f"[SamanthaWorker] Grace period: {self._idle_timeout}s")
				self._wake_event.wait(timeout=self._idle_timeout)
				if self._wake_event.is_set() and self._running:
					self._wake_event.clear()
					# More work arrived during grace — continue draining
					while self._running:
						task = qm.pop_next_task(allowed_sources=[SAMANTHA_SOURCE])
						if not task:
							break
						self._current_task_id = task["id"]
						self._health_ts = time.time()
						self._process_task(qm, task, port)
						self._current_task_id = None

		finally:
			self._shutdown_samantha()

	def _boot_samantha(self) -> Optional[int]:
		"""Boot Samantha on-demand. Returns port or None on failure."""
		try:
			from red_pill.inference.samantha_on_demand import (
				_EPHEMERAL_PORT,
				_is_hypervisor_alive,
				_is_port_open,
				_start_ephemeral,
			)

			if _is_hypervisor_alive():
				logger.info("[SamanthaWorker] Using persistent Hypervisor (port 8760)")
				return 8760

			if _is_port_open(_EPHEMERAL_PORT):
				logger.info(f"[SamanthaWorker] Port {_EPHEMERAL_PORT} already in use — reusing")
				return _EPHEMERAL_PORT

			self._ephemeral_proc = _start_ephemeral()
			if self._ephemeral_proc:
				self._stats["boots"] += 1
				logger.info(f"[SamanthaWorker] Ephemeral boot #{self._stats['boots']} on port {_EPHEMERAL_PORT}")
				return _EPHEMERAL_PORT
			else:
				logger.error("[SamanthaWorker] Ephemeral boot failed")
				return None
		except Exception as e:
			logger.error(f"[SamanthaWorker] Boot error: {e}")
			return None

	def _shutdown_samantha(self) -> None:
		"""Shutdown ephemeral Samantha if we booted it."""
		if self._ephemeral_proc:
			try:
				from red_pill.inference.samantha_on_demand import _stop_ephemeral

				_stop_ephemeral(self._ephemeral_proc)
				logger.info(f"[SamanthaWorker] Ephemeral shutdown. Session stats: {self._stats}")
			except Exception as e:
				logger.error(f"[SamanthaWorker] Shutdown error: {e}")
			self._ephemeral_proc = None

	def _process_task(self, qm, task: Dict[str, Any], port: int) -> None:
		"""Process a single task."""
		task_id = task["id"]
		payload = task["payload"]
		action = payload.get("action", "unknown")

		handler = _HANDLERS.get(action)
		if not handler:
			logger.warning(f"[SamanthaWorker] No handler for '{action}'. Marking failed.")
			qm.mark_failed(task_id, f"Unknown action: {action}")
			self._stats["failed"] += 1
			return

		try:
			from red_pill.inference.samantha_on_demand import _call_llm

			def samantha_fn(prompt: str, system_prompt: str = "", max_tokens: int = 300) -> Optional[str]:
				return _call_llm(port, prompt, system_prompt, max_tokens)

			logger.info(f"[SamanthaWorker] Processing {task_id}: {action}")
			result = handler(payload, samantha_fn)

			if result.get("status") == "completed":
				payload["result"] = result
				qm.mark_completed(task_id)
				self._stats["processed"] += 1
				logger.info(f"[SamanthaWorker] ✓ {task_id} completed")

				# Post-processing callbacks
				self._run_callback(action, payload, result)

			elif result.get("status") == "skipped":
				qm.mark_completed(task_id)
				self._stats["processed"] += 1
				logger.info(f"[SamanthaWorker] ○ {task_id} skipped: {result.get('reason')}")
			else:
				qm.mark_failed(task_id, result.get("reason", "Non-success status"))
				self._stats["failed"] += 1

		except Exception as e:
			logger.error(f"[SamanthaWorker] ✗ {task_id} crashed: {e}")
			qm.mark_failed(task_id, str(e))
			self._stats["failed"] += 1

	def _run_callback(self, action: str, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
		"""Post-processing callbacks after task completion."""
		if action == "compact_session":
			session_id = payload.get("session_id", "")
			summary = result.get("summary", "")
			channel_user_id = payload.get("channel_user_id", "")
			if session_id and summary and channel_user_id:
				try:
					from red_pill.plugins.antigravity_ide.telegram_session import TelegramSessionManager

					tsm = TelegramSessionManager()
					new_session = tsm.create_session(
						channel_user_id=channel_user_id,
						title=f"Compacted conversation (from {session_id[:8]})",
					)
					new_id = new_session["id"]
					tsm.append_message(new_id, "user", f"[Resumen de la sesión anterior]: {summary}")
					tsm.append_message(
						new_id, "assistant", "Entendido. He archivado el historial en el Bünker y consolidado el contexto. Continuemos."
					)

					# Mark old session for purge
					old_session = tsm.get_session(session_id)
					if old_session:
						old_session["status"] = "pending_purge"
						tsm.save_session(session_id, old_session)

					result["new_session_id"] = new_id
					logger.info(f"[SamanthaWorker] Compaction callback: {session_id[:8]} → {new_id}")
				except Exception as e:
					logger.error(f"[SamanthaWorker] Compaction callback failed: {e}")

	def _fail_all_pending(self, qm, reason: str) -> None:
		"""Mark all pending Samantha tasks as failed (used when boot fails)."""
		while True:
			task = qm.pop_next_task(allowed_sources=[SAMANTHA_SOURCE])
			if not task:
				break
			qm.mark_failed(task["id"], reason)
			self._stats["failed"] += 1
		logger.warning(f"[SamanthaWorker] All pending tasks failed: {reason}")
