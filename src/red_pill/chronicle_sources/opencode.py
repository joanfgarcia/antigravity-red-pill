"""Fuente opencode: sesiones del SQLite local (`~/.local/share/opencode/opencode.db`)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)


class OpencodeSourcePlugin(ChronicleSourcePlugin):
	"""Lee session/message/part del SQLite de opencode y los normaliza.

	El contenido vive en la tabla `part` (type: text | tool | reasoning |
	step-start | step-finish | compaction); solo text y tool aportan narrativa —
	el tool se compacta al marcador [TOOL: ...] del plugin de Claude Code.
	"""

	name = "opencode"
	session_prefix = "opencode:"

	def __init__(self, db_path: Optional[Path] = None):
		self.db_path = Path(db_path) if db_path else Path.home() / ".local" / "share" / "opencode" / "opencode.db"

	def _connect(self) -> sqlite3.Connection:
		# mode=ro: jamás escribir en la base de otro proceso; a las 04:00 opencode
		# suele estar cerrado, pero si está vivo el WAL sigue siendo legible.
		return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

	def discover(self) -> List[Tuple[str, int]]:
		if not self.db_path.exists():
			logger.info(f"[{self.name}] Database not found: {self.db_path}")
			return []
		try:
			con = self._connect()
			try:
				rows = con.execute("SELECT session_id, COUNT(*) FROM message GROUP BY session_id ORDER BY session_id").fetchall()
			finally:
				con.close()
		except sqlite3.Error as e:
			logger.warning(f"[{self.name}] Could not read database: {e}")
			return []
		return [(str(sid), int(count)) for sid, count in rows if sid]

	def _render_part(self, part: Dict[str, Any]) -> str:
		p_type = part.get("type")
		if p_type == "text":
			return part.get("text", "")
		if p_type == "tool":
			from red_pill.metabolism.chronicle.claude_code_plugin import _render_tool_use

			state = part.get("state") or {}
			return _render_tool_use(part.get("tool", ""), state.get("input") or {})
		return ""  # reasoning/step-start/step-finish/compaction: sin valor narrativo

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		con = self._connect()
		try:
			msg_rows = con.execute(
				"SELECT id, data, time_created FROM message WHERE session_id = ? ORDER BY time_created, id",
				(conversation_id,),
			).fetchall()
			part_rows = con.execute(
				"SELECT message_id, data FROM part WHERE session_id = ? ORDER BY time_created, id",
				(conversation_id,),
			).fetchall()
		finally:
			con.close()

		parts_by_message: Dict[str, List[Dict[str, Any]]] = {}
		for message_id, raw in part_rows:
			try:
				parts_by_message.setdefault(message_id, []).append(json.loads(raw))
			except Exception:
				continue

		messages: List[Dict[str, Any]] = []
		for message_id, raw, time_created in msg_rows:
			try:
				data = json.loads(raw)
			except Exception:
				continue
			role = data.get("role")
			if role not in ("user", "assistant"):
				continue

			rendered = [self._render_part(p) for p in parts_by_message.get(message_id, [])]
			content = "\n".join(chunk for chunk in rendered if chunk.strip())
			if not content.strip():
				continue

			# time.created viene en epoch ms; el ingester acepta epoch en segundos
			ts_ms = (data.get("time") or {}).get("created") or time_created
			messages.append({"role": role, "content": content, "timestamp": ts_ms / 1000.0 if ts_ms else None})

		return messages
