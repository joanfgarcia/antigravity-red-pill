"""Fuente Claude Code: transcripts JSONL de `~/.claude/projects/<proyecto>/*.jsonl`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin, canonical_ts
from red_pill.core.origins import PROVIDER_CLAUDE, telegram_sessions

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
		telegram = telegram_sessions(PROVIDER_CLAUDE)
		discovered = []
		for cid, path in self._index_sessions().items():
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
		"""El directorio del proyecto ES el workspace slug (`-home-joan-Workspace`, ...)."""
		path = self._paths.get(conversation_id) or self._index_sessions().get(conversation_id)
		return path.parent.name if path else None

	def _transcript_path(self, conversation_id: str) -> Optional[Path]:
		path = self._paths.get(conversation_id)
		if path is None:
			path = self._index_sessions().get(conversation_id)
		return path if path is not None and path.exists() else None

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		path = self._transcript_path(conversation_id)
		if path is None:
			raise FileNotFoundError(f"[{self.name}] Transcript not found for session {conversation_id}")
		return self._parse_transcript(path)

	def export_raw(self, conversation_id: str, dest_dir: Path) -> Optional[Path]:
		import shutil

		path = self._transcript_path(conversation_id)
		if path is None:
			return None
		dest = dest_dir / "raw.jsonl"
		shutil.copy2(path, dest)
		return dest

	def load_raw(self, raw_file: Path) -> List[Dict[str, Any]]:
		return self._parse_transcript(raw_file)

	def load_canonical(self, conversation_id: str) -> List[Dict[str, Any]]:
		"""Turnos con `tool_use`/`tool_result` nativos (pareja call ↔ resultado)."""
		path = self._transcript_path(conversation_id)
		if path is None:
			raise FileNotFoundError(f"[{self.name}] Transcript not found for session {conversation_id}")
		return self._parse_transcript_canonical(path)

	@staticmethod
	def _block_text(value: Any) -> str:
		if isinstance(value, str):
			return value
		if isinstance(value, list):
			return "\n".join(
				b.get("text", "") for b in value if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
			)
		return ""

	def _parse_transcript_canonical(self, path: Path) -> List[Dict[str, Any]]:
		turns: List[Dict[str, Any]] = []
		with open(path, "r", encoding="utf-8") as f:
			for line in f:
				line = line.strip()
				if not line:
					continue
				try:
					record = json.loads(line)
				except json.JSONDecodeError:
					continue
				if record.get("isSidechain") is True or record.get("isMeta") is True:
					continue
				r_type = record.get("type")
				if r_type not in ("user", "assistant"):
					continue
				message = record.get("message", {})
				ts = canonical_ts(record.get("timestamp"))
				ref = str(record.get("uuid") or message.get("id") or "")
				model = message.get("model")
				content = message.get("content")
				if r_type == "user":
					if isinstance(content, str):
						if content.strip():
							turns.append(
								{
									"role": "user",
									"content": content,
									"tool_calls": None,
									"tool_call_id": None,
									"model": model,
									"ts": ts,
									"source_ref": ref,
								}
							)
						continue
					text_parts: List[str] = []
					for index, block in enumerate(content if isinstance(content, list) else []):
						if not isinstance(block, dict):
							continue
						if block.get("type") == "text" and block.get("text"):
							text_parts.append(block["text"])
						elif block.get("type") == "tool_result":
							call_id = str(block.get("tool_use_id") or "")
							turns.append(
								{
									"role": "tool",
									"content": self._block_text(block.get("content")),
									"tool_calls": None,
									"tool_call_id": call_id,
									"model": model,
									"ts": ts,
									"source_ref": f"{ref}:tool:{call_id or index}",
								}
							)
					if text_parts:
						turns.append(
							{
								"role": "user",
								"content": "\n".join(text_parts),
								"tool_calls": None,
								"tool_call_id": None,
								"model": model,
								"ts": ts,
								"source_ref": ref,
							}
						)
					continue
				text_parts = []
				tool_calls = []
				for block in content if isinstance(content, list) else []:
					if not isinstance(block, dict):
						continue
					if block.get("type") == "text" and block.get("text"):
						text_parts.append(block["text"])
					elif block.get("type") == "tool_use":
						tool_calls.append(
							{
								"id": str(block.get("id") or ""),
								"type": "function",
								"function": {
									"name": str(block.get("name") or ""),
									"arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
								},
							}
						)
				text = "\n".join(text_parts) or None
				if text or tool_calls:
					turns.append(
						{
							"role": "assistant",
							"content": text,
							"tool_calls": tool_calls or None,
							"tool_call_id": None,
							"model": model,
							"ts": ts,
							"source_ref": ref,
						}
					)
		return turns

	def _parse_transcript(self, path: Path) -> List[Dict[str, Any]]:
		from red_pill.utils.chronicle_render import extract_assistant_blocks, extract_user_content

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
