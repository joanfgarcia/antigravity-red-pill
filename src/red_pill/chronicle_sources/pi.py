"""Fuente Pi (pi-coding-agent): sesiones JSONL de `~/.pi/agent/sessions/`.

Formato (v3, verificado contra pi-coding-agent 0.85.1): la primera línea es el
header `{"type":"session",...}`; el resto son entries en árbol con `timestamp`
ISO. Solo importan `type == "message"` con `message.role` en (user, assistant);
el `toolResult` se compacta a `[TOOL: <toolName>] <texto>` para que el ruido de
herramientas no entre verbatim al Búnker. `bashExecution`/`custom`/
`branchSummary`/`compactionSummary` se omiten.

OJO unidades: el `message.timestamp` es Unix **ms**; aquí se usa el `timestamp`
del entry (ISO), consistente con claude_code/opencode.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin, canonical_ts
from red_pill.core.origins import PROVIDER_PI, telegram_sessions

logger = logging.getLogger(__name__)


def _text_of(content: Any) -> str:
	"""Extrae texto de `content` (str | bloques [{type:text,...}])."""
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
	return ""


class PiSourcePlugin(ChronicleSourcePlugin):
	"""Normaliza las sesiones de Pi a mensajes {role, content, timestamp}."""

	name = "pi"
	session_prefix = "pi:"

	def __init__(self, base_dir: Optional[Path] = None):
		self.base_dir = Path(base_dir) if base_dir else Path.home() / ".pi" / "agent" / "sessions"
		self._paths: Dict[str, Path] = {}

	def _index_sessions(self) -> Dict[str, Path]:
		self._paths = {}
		if not self.base_dir.is_dir():
			logger.info(f"[{self.name}] Sessions dir not found: {self.base_dir}")
			return self._paths
		for session_file in sorted(self.base_dir.rglob("*.jsonl")):
			# Clave de Memento: ruta relativa sin extensión (estable, incluye cwd).
			cid = str(session_file.relative_to(self.base_dir).with_suffix(""))
			self._paths[cid] = session_file
			# El bridge/registry usa el UUID del header (sufijo tras el último `_`):
			# se indexa también para que `sync_originator(pi:<uuid>)` lo encuentre.
			uuid = session_file.stem.rsplit("_", 1)[-1]
			if uuid and uuid != cid:
				self._paths.setdefault(uuid, session_file)
		return self._paths

	def _session_path(self, conversation_id: str) -> Optional[Path]:
		path = self._paths.get(conversation_id)
		if path is None:
			path = self._index_sessions().get(conversation_id)
		return path if path is not None and path.exists() else None

	def discover(self) -> List[Tuple[str, int]]:
		telegram = telegram_sessions(PROVIDER_PI)
		discovered = []
		seen = set()
		for cid, path in self._index_sessions().items():
			if path in seen:
				continue  # el alias UUID no duplica la conversación
			seen.add(path)
			if cid in telegram:
				continue
			try:
				with open(path, "rb") as f:
					step_count = sum(1 for _ in f)
				discovered.append((cid, step_count))
			except Exception as e:
				logger.warning(f"[{self.name}] Could not read {path.name}: {e}")
		return discovered

	def workspace_of(self, conversation_id: str) -> Optional[str]:
		"""El slug `--<cwd-slug>--` del directorio (el cwd donde corrió Pi)."""
		path = self._session_path(conversation_id)
		return path.parent.name if path else None

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		path = self._session_path(conversation_id)
		if path is None:
			raise FileNotFoundError(f"[{self.name}] Session not found: {conversation_id}")
		return self._parse_session(path)

	def export_raw(self, conversation_id: str, dest_dir: Path) -> Optional[Path]:
		"""Copia verbatim el JSONL de la sesión a `raw/raw.jsonl` (regeneración sin store)."""
		path = self._session_path(conversation_id)
		if path is None:
			return None
		dest = dest_dir / "raw.jsonl"
		shutil.copy2(path, dest)
		return dest

	def load_raw(self, raw_file: Path) -> List[Dict[str, Any]]:
		return self._parse_session(raw_file)

	def load_canonical(self, conversation_id: str) -> List[Dict[str, Any]]:
		"""Turnos con `toolCall`/`toolResult` nativos (pareja call ↔ resultado)."""
		path = self._session_path(conversation_id)
		if path is None:
			raise FileNotFoundError(f"[{self.name}] Session not found: {conversation_id}")
		return self._parse_session_canonical(path)

	def _parse_session_canonical(self, path: Path) -> List[Dict[str, Any]]:
		turns: List[Dict[str, Any]] = []
		with open(path, "r", encoding="utf-8") as f:
			for index, line in enumerate(f):
				line = line.strip()
				if not line:
					continue
				try:
					record = json.loads(line)
				except json.JSONDecodeError:
					continue
				if record.get("type") != "message":
					continue
				msg = record.get("message", {})
				role = msg.get("role")
				ts = canonical_ts(record.get("timestamp"))
				ref = str(record.get("id") or f"{path.stem}:{index}")
				model = msg.get("model")
				content = msg.get("content")
				if role == "toolResult":
					turns.append(
						{
							"role": "tool",
							"content": _text_of(content),
							"tool_calls": None,
							"tool_call_id": msg.get("toolCallId"),
							"model": model,
							"ts": ts,
							"source_ref": ref,
						}
					)
					continue
				if role not in ("user", "assistant"):
					continue
				texts: List[str] = []
				tool_calls: List[Dict[str, Any]] = []
				for block in content if isinstance(content, list) else []:
					if not isinstance(block, dict):
						continue
					if block.get("type") == "text" and block.get("text"):
						texts.append(block["text"])
					elif block.get("type") == "toolCall":
						args = block.get("arguments")
						if not isinstance(args, str):
							args = json.dumps(args or {}, ensure_ascii=False)
						tool_calls.append(
							{
								"id": str(block.get("id") or ""),
								"type": "function",
								"function": {"name": str(block.get("name") or ""), "arguments": args},
							}
						)
				text = "\n".join(texts) or None
				if isinstance(content, str):
					text = content if content.strip() else None
				if text or tool_calls:
					turns.append(
						{
							"role": role,
							"content": text,
							"tool_calls": tool_calls or None,
							"tool_call_id": None,
							"model": model,
							"ts": ts,
							"source_ref": ref,
						}
					)
		return turns

	def _parse_session(self, path: Path) -> List[Dict[str, Any]]:
		messages: List[Dict[str, Any]] = []
		with open(path, "r", encoding="utf-8") as f:
			for line in f:
				line = line.strip()
				if not line:
					continue
				try:
					record = json.loads(line)
				except json.JSONDecodeError:
					continue  # línea parcial (sesión viva) o corrupta
				if record.get("type") != "message":
					continue  # header/compaction/branch_summary/model_change/...: ruido de harness
				msg = record.get("message", {})
				role = msg.get("role")
				# Timestamp del ENTRY (ISO): el message.timestamp es Unix ms y
				# variaría las unidades frente al resto de fuentes.
				ts = record.get("timestamp")
				if role in ("user", "assistant"):
					text = _text_of(msg.get("content"))
					if text.strip():
						messages.append({"role": role, "content": text, "timestamp": ts})
				elif role == "toolResult":
					text = _text_of(msg.get("content"))
					if text.strip():
						messages.append(
							{
								"role": "assistant",
								"content": f"[TOOL: {msg.get('toolName') or '?'}] {text[:500]}",
								"timestamp": ts,
							}
						)
				# bashExecution/custom/branchSummary/compactionSummary: se omiten
		return messages
