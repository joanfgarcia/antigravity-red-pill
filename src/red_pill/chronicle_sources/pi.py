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

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)


def _text_of(content: Any) -> str:
	"""Extrae texto de `content` (str | bloques [{type:text,...}])."""
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return "\n".join(
			b.get("text", "")
			for b in content
			if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
		)
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
			# clave estable entre barridos: ruta relativa sin extensión
			cid = str(session_file.relative_to(self.base_dir).with_suffix(""))
			self._paths[cid] = session_file
		return self._paths

	def _session_path(self, conversation_id: str) -> Optional[Path]:
		path = self._paths.get(conversation_id)
		if path is None:
			path = self._index_sessions().get(conversation_id)
		return path if path is not None and path.exists() else None

	def discover(self) -> List[Tuple[str, int]]:
		discovered = []
		for cid, path in self._index_sessions().items():
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
