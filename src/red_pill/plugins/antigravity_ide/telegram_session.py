import datetime
import json
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from red_pill.core.paths import get_data_dir, get_staging_dir

logger = logging.getLogger(__name__)


class TelegramSessionManager:
	"""
	Manages local, disk-based conversation history for Telegram.
	Stores history under XDG data dir to preserve context headlessly.
	Ingests via STAGING_DIR when compacted or marked for deletion.
	"""

	def __init__(self):
		self.conv_dir = get_data_dir() / "telegram_conversations"
		self.conv_dir.mkdir(parents=True, exist_ok=True)
		self.staging_dir = get_staging_dir()

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
		self.save_session(session_id, session)
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
		self.save_session(session_id, session)
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

	def copy_to_staging(self, session_id: str) -> bool:
		session = self.get_session(session_id)
		if not session:
			return False
		staging_path = self.staging_dir / f"{session_id}.json"
		try:
			with open(staging_path, "w", encoding="utf-8") as f:
				json.dump(session, f, indent=2)
			logger.info(f"[TelegramSession] Copied session {session_id} to staging for ingestion")
			return True
		except Exception as e:
			logger.error(f"[TelegramSession] Failed to copy session {session_id} to staging: {e}")
			return False

	def mark_for_deletion(self, session_id: str) -> bool:
		session = self.get_session(session_id)
		if not session:
			return False
		session["status"] = "pending_purge"
		session["summary"]["lastUpdatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
		self.save_session(session_id, session)
		# Copy to staging to guarantee sleep cycle ingests it before Janitor deletes it
		self.copy_to_staging(session_id)
		logger.info(f"[TelegramSession] Session {session_id} marked as pending_purge and copied to staging")
		return True

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

		steps = session.get("steps", [])
		total_chars = sum(len(s.get("message", {}).get("text", "")) for s in steps)

		if len(steps) < MAX_STEPS and total_chars < MAX_CHARS:
			return None

		logger.info(f"[TelegramSession] Enqueueing compaction for {session_id} ({len(steps)} steps, {total_chars} chars)")

		# 1. Archive the old session in Qdrant (by copying to staging)
		self.copy_to_staging(session_id)

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

	def run_janitor_sweep(self) -> int:
		"""
		Checks for sessions marked as pending_purge.
		If they are present in Qdrant collections (meaning Chronicle has ingested them),
		permanently delete them from disk.
		"""
		purged_count = 0
		try:
			from qdrant_client.models import FieldCondition, Filter, MatchValue

			from red_pill.memory import MemoryManager

			# Lazy initialize MemoryManager
			memory_mgr = MemoryManager()
			client = memory_mgr.client
		except Exception as e:
			logger.warning(f"[TelegramSession] Janitor skipped (cannot connect to MemoryManager): {e}")
			return 0

		for p in self.conv_dir.glob("*.json"):
			try:
				with open(p, "r", encoding="utf-8") as f:
					sess = json.load(f)
				if sess.get("status") == "pending_purge":
					session_id = sess.get("id")

					# Verify if session exists in Qdrant (Archived)
					archived = False
					for coll in ["work_memories", "social_memories"]:
						try:
							res, _ = client.scroll(
								collection_name=coll,
								scroll_filter=Filter(must=[FieldCondition(key="metadata.source_buffer_id", match=MatchValue(value=session_id))]),
								limit=1,
							)
							if res:
								archived = True
								break
						except Exception:
							continue

					if archived:
						p.unlink()
						purged_count += 1
						logger.info(f"[TelegramSession] Janitor purged archived session: {session_id}")
			except Exception as e:
				logger.error(f"[TelegramSession] Janitor failed processing {p.name}: {e}")

		return purged_count
