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
		session["steps"].append({"intent": "USER" if role.lower() == "user" else "ASSISTANT", "message": {"text": text}})
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

	def trigger_compaction(self, session_id: str, bridge) -> Optional[str]:
		"""Compacts history if it is too long (N > 16 steps). Ingests old context, creates a new session."""
		session = self.get_session(session_id)
		if not session or len(session.get("steps", [])) < 16:
			return None

		logger.info(f"[TelegramSession] Triggering compaction for {session_id}")

		# 1. Archive the old session in Qdrant (by copying to staging)
		self.copy_to_staging(session_id)

		# 2. Ask model via AgyBridge to summarize conversation context
		history_text = self.get_history_prompt(session)
		prompt_summary = (
			"Resume la siguiente conversación de Telegram entre el operador (Joan) y el agente (Aleth). "
			"Crea un resumen técnico y de progreso conciso para usarlo como contexto en el siguiente turno. "
			"Sé directo y resume los puntos clave de decisión y tareas pendientes.\n\n"
			f"{history_text}"
		)

		summary = "Resumen de contexto consolidado."
		try:
			res = bridge.prompt(prompt_summary, timeout=120)
			if res.ok and res.response:
				summary = res.response.strip()
				logger.info("[TelegramSession] Compaction summary generated successfully")
		except Exception as e:
			logger.error(f"[TelegramSession] Compaction synthesis failed: {e}")

		# 3. Create new session with the summary
		new_session = self.create_session(channel_user_id=session["channel_user_id"], title=f"Compacted conversation (from {session_id[:8]})")
		new_id = new_session["id"]

		# Inyectamos el resumen en el nuevo historial
		self.append_message(new_id, "user", f"[Resumen de la sesión anterior]: {summary}")
		self.append_message(new_id, "assistant", "Entendido. He archivado el historial en el Bünker y consolidado el contexto. Continuemos.")

		# También marcamos la vieja sesión para purgarla, ya que ya la copiamos a staging
		session["status"] = "pending_purge"
		self.save_session(session_id, session)

		return str(new_id) if new_id else None

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
