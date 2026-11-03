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

	@staticmethod
	def _has_v2(con: sqlite3.Connection) -> bool:
		"""¿La DB ya está en el esquema v2 (`session_message`)?"""
		try:
			row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_message'").fetchone()
			if not row:
				return False
			count = con.execute("SELECT COUNT(*) FROM session_message").fetchone()[0]
			return int(count) > 0
		except Exception:
			# No poder comprobarlo no es un error: se sigue por el camino v1.
			return False

	@staticmethod
	def _v2_turns(con: sqlite3.Connection, conversation_id: str) -> Tuple[List[Any], List[Any]]:
		"""Remapea `session_message` (v2) a la forma message/part que ya sabemos pintar.

		v2 guarda todo en una tabla: el rol es la columna `type`, el texto del user va
		en `data.text` y los trozos del assistant en `data.content`, con las tools
		como `{name, state}` (no `{tool, state}`). Sin este puente, toda sesión creada
		después de la migración v2 quedaba invisible para Memento (medido 2026-11-02:
		última sesión renderizada el 27-oct y 793 mensajes nuevos sin ver).
		"""
		msg_rows: List[Any] = []
		part_rows: List[Any] = []
		rows = con.execute(
			"SELECT id, type, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq",
			(conversation_id,),
		).fetchall()
		for message_id, mtype, time_created, raw in rows:
			if mtype not in ("user", "assistant"):
				continue
			try:
				data = json.loads(raw)
			except Exception:
				continue
			msg_rows.append((message_id, json.dumps({"role": mtype, "time": {"created": time_created}}), time_created))
			if mtype == "user":
				part_rows.append((message_id, json.dumps({"type": "text", "text": data.get("text", "") or ""})))
				continue
			for part in data.get("content") or []:
				kind = part.get("type")
				if kind == "tool":
					part_rows.append(
						(
							message_id,
							json.dumps({"type": "tool", "tool": part.get("name"), "state": part.get("state") or {}}),
						)
					)
				elif kind == "text":
					part_rows.append((message_id, json.dumps({"type": "text", "text": part.get("text", "") or ""})))
		return msg_rows, part_rows

	def discover(self) -> List[Tuple[str, int]]:
		if not self.db_path.exists():
			logger.info(f"[{self.name}] Database not found: {self.db_path}")
			return []
		try:
			con = self._connect()
			try:
				if self._has_v2(con):
					rows = con.execute(
						"SELECT session_id, COUNT(*) FROM session_message WHERE type IN ('user','assistant') GROUP BY session_id ORDER BY session_id"
					).fetchall()
				else:
					rows = con.execute("SELECT session_id, COUNT(*) FROM message GROUP BY session_id ORDER BY session_id").fetchall()
			finally:
				con.close()
		except sqlite3.Error as e:
			logger.warning(f"[{self.name}] Could not read database: {e}")
			return []
		# Precedencia provider-first (2026-11-03): si la sesión existe en el store
		# del provider, se renderiza desde aquí — venga de Telegram o no. El source
		# `telegram` solo sirve lo que ningún provider cubre (su store de
		# conversaciones), así que no hay doble render: el que tiene el raw manda.
		return [(str(sid), int(count)) for sid, count in rows if sid]

	def _render_part(self, part: Dict[str, Any]) -> str:
		p_type = part.get("type")
		if p_type == "text":
			return part.get("text", "") or ""
		if p_type == "tool":
			from red_pill.utils.chronicle_render import _render_tool_use

			state = part.get("state") or {}
			return _render_tool_use(part.get("tool", ""), state.get("input") or {})
		return ""  # reasoning/step-start/step-finish/compaction: sin valor narrativo

	def _fetch_rows(self, conversation_id: str) -> Tuple[List[Any], List[Any]]:
		con = self._connect()
		try:
			if self._has_v2(con):
				return self._v2_turns(con, conversation_id)
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
		return msg_rows, part_rows

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		msg_rows, part_rows = self._fetch_rows(conversation_id)
		return self._normalize_rows(msg_rows, part_rows)

	def export_raw(self, conversation_id: str, dest_dir: Path) -> Optional[Path]:
		"""Volcado JSON de las filas nativas message/part — suficiente para regenerar sin la DB."""
		msg_rows, part_rows = self._fetch_rows(conversation_id)
		if not msg_rows:
			return None
		dest = dest_dir / "raw.json"
		payload = {"session_id": conversation_id, "message_rows": [list(r) for r in msg_rows], "part_rows": [list(r) for r in part_rows]}
		dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
		return dest

	def load_raw(self, raw_file: Path) -> List[Dict[str, Any]]:
		data = json.loads(raw_file.read_text(encoding="utf-8"))
		return self._normalize_rows([tuple(r) for r in data.get("message_rows", [])], [tuple(r) for r in data.get("part_rows", [])])

	def load_canonical(self, conversation_id: str) -> List[Dict[str, Any]]:
		"""Turnos con tool-calls OpenAI nativos (pareja assistant.tool_calls ↔ tool)."""
		msg_rows, part_rows = self._fetch_rows(conversation_id)
		return self._normalize_rows_canonical(msg_rows, part_rows)

	def _tool_output(self, state: Dict[str, Any]) -> str:
		output = state.get("output")
		if output is None:
			return ""
		if isinstance(output, str):
			return output
		try:
			return json.dumps(output, ensure_ascii=False)
		except (TypeError, ValueError):
			return str(output)

	def _normalize_rows_canonical(self, msg_rows: List[Any], part_rows: List[Any]) -> List[Dict[str, Any]]:
		"""Como `_normalize_rows`, pero conserva `tool_calls`/`tool_call_id` intactos."""
		parts_by_message: Dict[str, List[Dict[str, Any]]] = {}
		for message_id, raw in part_rows:
			try:
				parts_by_message.setdefault(message_id, []).append(json.loads(raw))
			except Exception:
				continue

		turns: List[Dict[str, Any]] = []
		for message_id, raw, time_created in msg_rows:
			try:
				data = json.loads(raw)
			except Exception:
				continue
			role = data.get("role")
			if role not in ("user", "assistant"):
				continue
			ts_ms = (data.get("time") or {}).get("created") or time_created
			ts = float(ts_ms) / 1000.0 if ts_ms else 0.0
			model = data.get("modelID")
			parts = parts_by_message.get(message_id, [])

			text_chunks = [p.get("text", "") or "" for p in parts if p.get("type") == "text"]
			content = "\n".join(chunk for chunk in text_chunks if chunk.strip()) or None
			tool_parts = [p for p in parts if p.get("type") == "tool"]
			tool_calls = []
			for index, part in enumerate(tool_parts):
				call_id = str(part.get("callID") or f"{message_id}:{index}")
				tool_calls.append(
					{
						"id": call_id,
						"type": "function",
						"function": {
							"name": str(part.get("tool") or ""),
							"arguments": json.dumps(part.get("state", {}).get("input") or {}, ensure_ascii=False),
						},
					}
				)
			if content or tool_calls:
				turns.append(
					{
						"role": role,
						"content": content,
						"tool_calls": tool_calls or None,
						"tool_call_id": None,
						"model": model,
						"ts": ts,
						"source_ref": message_id,
					}
				)
			for call, part in zip(tool_calls, tool_parts):
				turns.append(
					{
						"role": "tool",
						"content": self._tool_output(part.get("state") or {}),
						"tool_calls": None,
						"tool_call_id": call["id"],
						"model": model,
						"ts": ts,
						"source_ref": f"{message_id}:tool:{call['id']}",
					}
				)
		return turns

	def _normalize_rows(self, msg_rows: List[Any], part_rows: List[Any]) -> List[Dict[str, Any]]:
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
