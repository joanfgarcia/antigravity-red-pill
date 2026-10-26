import datetime
import json
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional

from red_pill.core.paths import get_data_dir

logger = logging.getLogger(__name__)


class TelegramSessionManager:
	"""
	Manages local, disk-based conversation history for Telegram.
	Stores history under XDG data dir to preserve context headlessly.
	Single-writer: ya NO ingesta a staging (retirado); lo consume Memento.

	Con `TELEGRAM_SOUL_MAPPING_ENABLED` (o `soul_mapping=True`), la sesión se
	mapea a un alma estable y sus turnos se escriben en `session_mirror`; el
	compactor puede operar sobre ella sin cambiar aún el carril de resumen.
	"""

	def __init__(
		self,
		*,
		conv_dir: Optional[Path] = None,
		db_path: Optional[str] = None,
		soul_mapping: Optional[bool] = None,
	):
		self.conv_dir = Path(conv_dir) if conv_dir is not None else get_data_dir() / "telegram_conversations"
		self.conv_dir.mkdir(parents=True, exist_ok=True)
		self.db_path = db_path
		self.soul_mapping = soul_mapping

	def _mapping_enabled(self) -> bool:
		if self.soul_mapping is not None:
			return bool(self.soul_mapping)
		try:
			import red_pill.config as cfg

			return bool(getattr(cfg.get_config(), "TELEGRAM_SOUL_MAPPING_ENABLED", False))
		except Exception:
			return False

	def _soul_continuity(self, channel_user_id: str) -> str:
		"""Alma estable por usuario de Telegram (sobrevive a la rotación)."""
		return str(uuid.uuid5(uuid.NAMESPACE_URL, f"red-pill:telegram:{channel_user_id or 'unknown'}"))

	def _ensure_soul(self, session: dict) -> bool:
		if not self._mapping_enabled():
			return False
		changed = False
		if not session.get("continuity_id"):
			session["continuity_id"] = self._soul_continuity(str(session.get("channel_user_id") or ""))
			changed = True
		if not session.get("mission_id"):
			session["mission_id"] = "mission:telegram"
			changed = True
		return changed

	def _register_leg(self, session: dict) -> None:
		if not self._mapping_enabled():
			return
		try:
			from red_pill.session.store import SessionRegistry

			SessionRegistry(self.db_path).upsert_session(
				originator=f"telegram:{session['id']}",
				continuity_id=str(session["continuity_id"]),
				mission_id=str(session["mission_id"]),
				role="task",
				title=str((session.get("summary") or {}).get("summary") or "Telegram"),
			)
		except Exception as e:
			logger.warning(f"[TelegramSession] soul leg registration failed: {e}")

	def _mirror_turn(self, session: dict, role: str, text: str, index: int) -> None:
		if not self._mapping_enabled():
			return
		try:
			from red_pill.session.mirror import SessionMirror

			SessionMirror(self.db_path).append_turn(
				continuity_id=str(session["continuity_id"]),
				mission_id=str(session["mission_id"]),
				role=role,
				content=text,
				originator=f"telegram:{session['id']}",
				source="telegram",
				source_ref=f"telegram:{session['id']}:{index}",
				ts=time.time(),
				status="completed",
			)
		except Exception as e:
			logger.warning(f"[TelegramSession] mirror write failed: {e}")

	def _unregister_leg(self, session_id: str) -> None:
		if not self._mapping_enabled():
			return
		try:
			from red_pill.session.store import SessionRegistry

			SessionRegistry(self.db_path).unregister_session(f"telegram:{session_id}")
		except Exception as e:
			logger.warning(f"[TelegramSession] soul leg unregister failed: {e}")

	def _get_path(self, session_id: str) -> Path:
		return self.conv_dir / f"{session_id}.json"

	def get_session(self, session_id: str) -> Optional[dict]:
		path = self._get_path(session_id)
		if path.exists():
			try:
				with open(path, "r", encoding="utf-8") as f:
					return json.load(f) if path.exists() else None
			except Exception as e:
				logger.error(f"[TelegramSession] Failed to load session {session_id}: {e}")
		return None

	def create_session(self, channel_user_id: str, title: Optional[str] = None) -> dict:
		session_id = str(uuid.uuid4())
		session = {
			"id": session_id,
			"status": "active",
			"channel_user_id": channel_user_id,
			"summary": {
				"createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
				"lastUpdatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
				"summary": title or f"Telegram conversation with {channel_user_id}",
			},
			"steps": [],
		}
		self._ensure_soul(session)
		self.save_session(session_id, session)
		self._register_leg(session)
		return session

	def save_session(self, session_id: str, session: dict) -> None:
		path = self._get_path(session_id)
		try:
			with open(path, "w", encoding="utf-8") as f:
				json.dump(session, f, indent=2)
		except Exception as e:
			logger.error(f"[TelegramSession] Failed to save session {session_id}: {e}")

	def list_sessions(self, channel_user_id: str) -> List[dict]:
		"""List all active (not pending purge) sessions for a user, sorted by lastUpdatedAt desc."""
		sessions = []
		for p in self.conv_dir.glob("*.json"):
			try:
				with open(p, "r", encoding="utf-8") as f:
					sess = json.load(f)
				if sess.get("channel_user_id") == channel_user_id and sess.get("status") != "pending_purge":
					sessions.append(sess)
			except Exception:
				continue
		sessions.sort(key=lambda s: s.get("summary", {}).get("lastUpdatedAt", ""), reverse=True)
		return sessions

	def append_message(self, session_id: str, role: str, text: str) -> Optional[dict]:
		session = self.get_session(session_id)
		if not session:
			return None

		intent = "USER" if role.lower() == "user" else "ASSISTANT"

		# Hygiene: skip empty assistant responses (e.g. quota exhausted)
		if intent == "ASSISTANT" and not text.strip():
			logger.debug(f"[TelegramSession] Skipping empty assistant response for {session_id}")
			return session

		# Hygiene: deduplicate consecutive identical USER messages (e.g. repeated AWAKENINGs)
		steps = session.get("steps", [])
		if intent == "USER" and steps:
			last = steps[-1]
			if last.get("intent") == "USER" and last.get("message", {}).get("text", "") == text:
				logger.debug(f"[TelegramSession] Deduplicating identical USER message for {session_id}")
				return session

		session["steps"].append({"intent": intent, "message": {"text": text}})
		session["summary"]["lastUpdatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
		self._ensure_soul(session)
		self.save_session(session_id, session)
		self._mirror_turn(
			session,
			"user" if intent == "USER" else "assistant",
			text,
			len(session["steps"]),
		)
		return session

	def get_history_prompt(self, session: dict) -> str:
		"""Format conversation steps for model consumption."""
		lines = []
		for step in session.get("steps", []):
			role = step.get("intent", "USER")
			txt = step.get("message", {}).get("text", "")
			if txt:
				lines.append(f"{role}: {txt}")
		return "\n\n".join(lines)

	def mark_for_deletion(self, session_id: str) -> bool:
		session = self.get_session(session_id)
		if not session:
			return False
		session["status"] = "pending_purge"
		session["summary"]["lastUpdatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
		self.save_session(session_id, session)
		self._unregister_leg(session_id)
		logger.info(f"[TelegramSession] Session {session_id} marked as pending_purge")
		return True

	def _maybe_start_mirror_compaction(self, session: dict) -> None:
		"""Chequeo event-driven del espejo (tras un turno, no un poll).

		Con el mapeo y el compactor habilitados, estima el contexto en SQL
		(`estimate_context_tokens`) y encola el job durable si cruza el umbral
		del carril Telegram. No bloquea el turno ni lee/replaya el historial.
		"""
		if not self._mapping_enabled():
			return
		try:
			import red_pill.config as cfg

			conf = cfg.get_config()
			if not bool(getattr(conf, "SESSION_COMPACTOR_ENABLED", False)):
				return
			from red_pill.session.compactor import Compactor
			from red_pill.session.mirror import SessionMirror

			context_chars = max(400, int(getattr(conf, "TELEGRAM_COMPACTOR_CONTEXT_CHARS", 4000)))
			background_chars = max(1, int(getattr(conf, "TELEGRAM_COMPACTOR_BACKGROUND_CHARS", 800)))
			reserve_chars = max(1, int(getattr(conf, "TELEGRAM_COMPACTOR_RESERVE_CHARS", 400)))
			protect = max(0, int(getattr(conf, "TELEGRAM_COMPACTOR_PROTECT_LAST_N", 8)))
			compactor = Compactor(
				SessionMirror(self.db_path),
				background_tokens=max(1, int(background_chars / 3.2)),
				reserve_tokens=max(1, int(reserve_chars / 3.2)),
				protect_last_n=protect,
			)
			estimate = compactor.estimate_context_tokens(session["continuity_id"])
			budget = max(1, int(context_chars / 3.2))
			compactor.maybe_start(
				session["continuity_id"],
				mission_id=str(session.get("mission_id") or "mission:telegram"),
				protect_last_n=protect,
				estimated_tokens=estimate,
				budget_tokens=budget,
				reserve_tokens=compactor.reserve_tokens,
			)
		except Exception as e:
			logger.warning(f"[TelegramSession] mirror compaction check failed: {e}")

	def trigger_compaction(self, session_id: str, bridge=None) -> Optional[str]:
		"""Compacts history if too long (steps > 16) or too heavy (chars > 4000).

		Enqueues summarization to the Samantha Queue (local LLM, zero Flash cost).
		The actual summarization + session rotation happens asynchronously via
		the queue's post-processing callback.

		The `bridge` parameter is ignored (kept for backward compatibility).
		"""
		MAX_STEPS = 16
		MAX_CHARS = 4000

		session = self.get_session(session_id)
		if not session:
			return None
		self._maybe_start_mirror_compaction(session)

		steps = session.get("steps", [])
		total_chars = sum(len(s.get("message", {}).get("text", "")) for s in steps)

		if len(steps) < MAX_STEPS and total_chars < MAX_CHARS:
			return None

		# Dedup: una compactación ya encolada/en vuelo para esta sesión rotará la
		# sesión al completar — encolar otra solo duplica trabajo del LLM local.
		try:
			from red_pill.cognitive.queue_manager import CognitiveQueueManager

			existing = CognitiveQueueManager().find_task_by_payload_key(source="samantha", key="session_id", value=session_id)
			if existing:
				logger.info(f"[TelegramSession] Compaction already {existing['status']} for {session_id} ({existing['id'][:8]}) — skipping duplicate")
				return None
		except Exception as e:
			logger.warning(f"[TelegramSession] Compaction dedup check failed: {e} — enqueueing anyway")

		logger.info(f"[TelegramSession] Enqueueing compaction for {session_id} ({len(steps)} steps, {total_chars} chars)")

		# 2. Enqueue summarization to the Samantha Queue
		history_text = self.get_history_prompt(session)
		try:
			from red_pill.inference.samantha_worker import enqueue

			enqueue(
				action="compact_session",
				payload={
					"session_id": session_id,
					"channel_user_id": session.get("channel_user_id", ""),
					"history_text": history_text,
				},
				priority=7,
			)
			logger.info("[TelegramSession] Compaction enqueued for async processing via Samantha")
		except Exception as e:
			logger.error(f"[TelegramSession] Failed to enqueue compaction: {e}")

		# Note: session rotation happens in the queue's _run_callbacks()
		# after Samantha generates the summary. We don't return a new session ID
		# here because it's asynchronous now.
		return None

	def _is_archived(self, session_id: str) -> bool:
		"""¿La sesión está ya archivada en Memento y es seguro borrarla del disco?

		Se consulta el `memento_registry` acotado a la fuente `telegram` (los UUID
		crudos se repiten en otras fuentes —antigravity— y mirar todas daría
		falsos positivos). El drenaje legacy que estampaba `source_buffer_id` fue
		retirado (v8.0.0).

		Fail-safe: si no se puede verificar, NO se purga (preferimos retener a
		borrar algo no archivado).
		"""
		try:
			from red_pill.memento.registry import MementoRegistry

			if MementoRegistry().is_rendered(str(session_id), sources=["telegram"]):
				return True
			logger.info(f"[TelegramSession] {session_id} aún no renderizada en Memento; no se purga.")
			return False
		except Exception as e:
			logger.warning(f"[TelegramSession] no se pudo verificar Memento para {session_id}: {e}; no se purga.")
			return False

	def run_janitor_sweep(self) -> int:
		"""Purga del disco las sesiones `pending_purge` ya archivadas en Memento."""
		purged_count = 0
		for p in self.conv_dir.glob("*.json"):
			try:
				with open(p, "r", encoding="utf-8") as f:
					sess = json.load(f)
				if sess.get("status") == "pending_purge":
					session_id = sess.get("id")
					if self._is_archived(session_id):
						p.unlink()
						purged_count += 1
						logger.info(f"[TelegramSession] Janitor purged archived session: {session_id}")
			except Exception as e:
				logger.error(f"[TelegramSession] Janitor failed processing {p.name}: {e}")

		return purged_count
