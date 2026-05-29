"""
Samantha Queue Worker — Batch LLM task processor.

Lifecycle:
1. Check CognitiveQueue for pending tasks with source='samantha'
2. If tasks exist → boot Samantha (on-demand)
3. Drain all pending tasks sequentially
4. Shutdown Samantha if we booted her

Designed to be called from the worker poll loop or via a systemd timer.
"""

import json
import logging
from typing import Any, Callable, Dict, Optional

from red_pill.cognitive.queue_manager import CognitiveQueueManager

logger = logging.getLogger(__name__)

# ── Task handlers registry ────────────────────────────────
# Each handler receives (payload, samantha_fn) where samantha_fn
# is a callable: samantha_fn(prompt, system_prompt, max_tokens) -> str|None

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
	session_id = payload.get("session_id", "")
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

	return {"status": "completed", "summary": summary, "session_id": session_id}


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


# ── Queue operations ──────────────────────────────────────

SAMANTHA_SOURCE = "samantha"


def enqueue(action: str, payload: Dict[str, Any], priority: int = 5) -> str:
	"""Enqueue a task for Samantha processing.

	Args:
		action: Handler name (e.g. 'compact_session', 'classify', 'summarize')
		payload: Task-specific data
		priority: 1-10, higher = more urgent

	Returns:
		Task ID
	"""
	payload["action"] = action
	qm = CognitiveQueueManager()
	task_id = qm.enqueue_task(source=SAMANTHA_SOURCE, payload=payload, priority=priority)
	logger.info(f"[SamanthaQueue] Enqueued task {task_id}: {action}")
	return task_id


def drain_queue() -> int:
	"""
	Drain all pending Samantha tasks. Boot on-demand if needed.

	Returns number of tasks processed.
	"""
	qm = CognitiveQueueManager()
	processed = 0

	# Peek first to see if there's work before booting Samantha
	first_task = qm.pop_next_task(allowed_sources=[SAMANTHA_SOURCE])
	if not first_task:
		return 0

	logger.info("[SamanthaQueue] Tasks pending — initializing Samantha")

	# Boot Samantha (on-demand lifecycle)
	from red_pill.inference.samantha_on_demand import (
		_call_llm,
		_is_hypervisor_alive,
		_is_port_open,
		_start_ephemeral,
		_stop_ephemeral,
		_EPHEMERAL_PORT,
	)

	ephemeral_proc = None
	port = None

	if _is_hypervisor_alive():
		port = 8760
		logger.info("[SamanthaQueue] Using persistent Hypervisor on port 8760")
	else:
		if _is_port_open(_EPHEMERAL_PORT):
			port = _EPHEMERAL_PORT
			logger.info(f"[SamanthaQueue] Port {_EPHEMERAL_PORT} already in use — using it")
		else:
			ephemeral_proc = _start_ephemeral()
			if ephemeral_proc:
				port = _EPHEMERAL_PORT
			else:
				logger.error("[SamanthaQueue] Failed to boot Samantha — returning task to queue")
				qm.mark_failed(first_task["id"], "Samantha boot failed")
				return 0

	def samantha_fn(prompt: str, system_prompt: str = "", max_tokens: int = 300) -> Optional[str]:
		return _call_llm(port, prompt, system_prompt, max_tokens)

	try:
		# Process first task (already popped)
		processed += _process_task(qm, first_task, samantha_fn)

		# Drain remaining tasks
		while True:
			task = qm.pop_next_task(allowed_sources=[SAMANTHA_SOURCE])
			if not task:
				break
			processed += _process_task(qm, task, samantha_fn)

	finally:
		# Cleanup: stop ephemeral if we started it
		if ephemeral_proc:
			_stop_ephemeral(ephemeral_proc)
			logger.info(f"[SamanthaQueue] Drained {processed} tasks. Ephemeral Samantha stopped.")
		else:
			logger.info(f"[SamanthaQueue] Drained {processed} tasks. Persistent Hypervisor left running.")

	return processed


def _process_task(qm: CognitiveQueueManager, task: Dict[str, Any], samantha_fn: Callable) -> int:
	"""Process a single task from the queue."""
	task_id = task["id"]
	payload = task["payload"]
	action = payload.get("action", "unknown")

	handler = _HANDLERS.get(action)
	if not handler:
		logger.warning(f"[SamanthaQueue] No handler for action '{action}'. Marking failed.")
		qm.mark_failed(task_id, f"Unknown action: {action}")
		return 0

	try:
		logger.info(f"[SamanthaQueue] Processing task {task_id}: {action}")
		result = handler(payload, samantha_fn)

		if result.get("status") == "completed":
			# Store result in payload for consumers
			payload["result"] = result
			qm.mark_completed(task_id)
			logger.info(f"[SamanthaQueue] Task {task_id} completed successfully")

			# Post-processing callbacks (if any)
			_run_callbacks(action, payload, result)
			return 1
		elif result.get("status") == "skipped":
			qm.mark_completed(task_id)
			logger.info(f"[SamanthaQueue] Task {task_id} skipped: {result.get('reason')}")
			return 1
		else:
			qm.mark_failed(task_id, result.get("reason", "Handler returned non-success"))
			return 0
	except Exception as e:
		logger.error(f"[SamanthaQueue] Task {task_id} crashed: {e}")
		qm.mark_failed(task_id, str(e))
		return 0


def _run_callbacks(action: str, payload: Dict[str, Any], result: Dict[str, Any]) -> None:
	"""Post-processing callbacks after task completion."""
	if action == "compact_session":
		# Apply the compaction result to the TelegramSessionManager
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
				tsm.append_message(new_id, "assistant", "Entendido. He archivado el historial en el Bünker y consolidado el contexto. Continuemos.")

				# Mark old session for purge
				old_session = tsm.get_session(session_id)
				if old_session:
					old_session["status"] = "pending_purge"
					tsm.save_session(session_id, old_session)

				# Store new session ID for the caller
				result["new_session_id"] = new_id
				logger.info(f"[SamanthaQueue] Compaction callback applied: {session_id} → {new_id}")
			except Exception as e:
				logger.error(f"[SamanthaQueue] Compaction callback failed: {e}")
