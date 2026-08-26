"""Fuente Claude Code: transcripts JSONL de `~/.claude/projects/<proyecto>/*.jsonl`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)


class ClaudeCodeSourcePlugin(ChronicleSourcePlugin):
	"""Normaliza los transcripts de Claude Code a mensajes {role, content, timestamp}.

	Reutiliza los extractores del plugin de consolidación (extract_user_content /
	extract_assistant_blocks): mismos marcadores compactos [TOOL: ...] para que el
	ruido de herramientas no entre verbatim al Bünker.
	"""

	name = "claude_code"
	session_prefix = "claude_code:"

	def __init__(self, base_dir: Optional[Path] = None):
		self.base_dir = Path(base_dir) if base_dir else Path.home() / ".claude" / "projects"
		self._paths: Dict[str, Path] = {}

	def _index_sessions(self) -> Dict[str, Path]:
		"""Mapa conversation_id → fichero JSONL (el stem del transcript es el session uuid)."""
		self._paths = {}
		if not self.base_dir.is_dir():
			logger.info(f"[{self.name}] Projects dir not found: {self.base_dir}")
			return self._paths
		for proj_dir in sorted(self.base_dir.iterdir()):
			if not proj_dir.is_dir():
				continue
			for session_file in sorted(proj_dir.glob("*.jsonl")):
				self._paths[session_file.stem] = session_file
		return self._paths

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
		"""El directorio del proyecto ES el workspace slug (`-home-joan-Workspace`, ...)."""
		path = self._paths.get(conversation_id) or self._index_sessions().get(conversation_id)
		return path.parent.name if path else None

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		from red_pill.metabolism.chronicle.claude_code_plugin import extract_assistant_blocks, extract_user_content

		path = self._paths.get(conversation_id)
		if path is None:
			path = self._index_sessions().get(conversation_id)
		if path is None or not path.exists():
			raise FileNotFoundError(f"[{self.name}] Transcript not found for session {conversation_id}")

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

				# Cadena principal solo: los sidechains son subagentes, no diálogo
				if record.get("isSidechain") is True or record.get("isMeta") is True:
					continue

				r_type = record.get("type")
				ts = record.get("timestamp")

				if r_type == "user":
					text = extract_user_content(record.get("message", {}))
					if text.strip():
						messages.append({"role": "user", "content": text, "timestamp": ts})
				elif r_type == "assistant":
					blocks = extract_assistant_blocks(record.get("message", {}))
					text = "\n".join(b["message"]["text"] for b in blocks if b["message"]["text"].strip())
					if text.strip():
						messages.append({"role": "assistant", "content": text, "timestamp": ts})
				# resto (queue-operation, attachment, progress...) es ruido de harness

		return messages
