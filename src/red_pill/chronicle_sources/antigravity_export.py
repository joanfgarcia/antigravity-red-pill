"""Fuente antigravity_export: los transcripts MD congelados el 23-mar-2026.

`~/.gemini/antigravity/conversations_export/*.md` es una exportación manual de
las 47 conversaciones que existían aquel día — la era temprana (Reverie,
Gunslinger, los primeros AWAKENINGs) cuyo verbatim no sobrevive en ningún otro
store (los .pb se podaron, el LS solo retiene el working set y la vía AES nunca
funcionó). Formato: metadatos (Cascade ID/Steps/Created) + turnos
"## 🧑 User" / "## 🤖 Assistant" con timestamp y bloques "### 🔧 Tool:"
embebidos. Corpus congelado: el delta del migrate lo toca una sola vez.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)

_TURN_RE = re.compile(r"^## (🧑 User|🤖 Assistant)\s+`([^`]+)`")
_META_RE = re.compile(r"^- \*\*(Cascade ID|Steps|Workspace)\*\*:\s*`?([^`\n]+)`?\s*$")
_FRACTION_RE = re.compile(r"(\.\d{1,6})\d*")


def _iso_to_epoch(ts: str) -> Optional[float]:
	"""ISO con nanosegundos (9 dígitos, fromisoformat solo traga 6) → epoch."""
	try:
		trimmed = _FRACTION_RE.sub(r"\1", ts.replace("Z", "+00:00"))
		parsed = datetime.fromisoformat(trimmed)
		if parsed.tzinfo is None:
			parsed = parsed.replace(tzinfo=timezone.utc)
		return parsed.timestamp()
	except ValueError:
		return None


class AntigravityExportSourcePlugin(ChronicleSourcePlugin):
	"""Parsea los transcripts MD del export manual del 23-mar (era temprana verbatim)."""

	name = "antigravity_export"
	session_prefix = ""  # cascade_ids desnudos, como la fuente antigravity viva

	def __init__(self, export_dir: Optional[Path] = None):
		self.export_dir = Path(export_dir) if export_dir else Path.home() / ".gemini" / "antigravity" / "conversations_export"
		self._files: Dict[str, Path] = {}

	def _metadata_of(self, md_file: Path) -> Dict[str, str]:
		meta: Dict[str, str] = {}
		try:
			with open(md_file, encoding="utf-8") as f:
				for i, line in enumerate(f):
					if i > 20:
						break
					match = _META_RE.match(line.strip())
					if match:
						meta[match.group(1)] = match.group(2).strip()
		except Exception:
			pass
		return meta

	def _index_files(self) -> Dict[str, Path]:
		self._files = {}
		if not self.export_dir.is_dir():
			logger.info(f"[{self.name}] Export dir not found: {self.export_dir}")
			return self._files
		for md_file in sorted(self.export_dir.glob("*.md")):
			cascade_id = self._metadata_of(md_file).get("Cascade ID")
			if cascade_id:  # los .md sin Cascade ID son documentos (crónicas), no conversaciones
				self._files[cascade_id] = md_file
		return self._files

	def discover(self) -> List[Tuple[str, int]]:
		discovered = []
		for cascade_id, md_file in self._index_files().items():
			steps = self._metadata_of(md_file).get("Steps", "0")
			discovered.append((cascade_id, int(steps) if steps.isdigit() else 0))
		return discovered

	def workspace_of(self, conversation_id: str) -> Optional[str]:
		md_file = self._files.get(conversation_id) or self._index_files().get(conversation_id)
		if md_file is None:
			return None
		workspace = self._metadata_of(md_file).get("Workspace", "")
		return workspace.rstrip("/").rsplit("/", 1)[-1] or None if workspace else None

	def _parse_transcript(self, md_file: Path) -> List[Dict[str, Any]]:
		messages: List[Dict[str, Any]] = []
		role: Optional[str] = None
		timestamp: Optional[float] = None
		buffer: List[str] = []

		def flush() -> None:
			if role is None:
				return
			content = "\n".join(buffer).strip()
			if content:
				messages.append({"role": role, "content": content, "timestamp": timestamp})

		for line in md_file.read_text(encoding="utf-8").split("\n"):
			match = _TURN_RE.match(line)
			if match:
				flush()
				role = "user" if "User" in match.group(1) else "assistant"
				timestamp = _iso_to_epoch(match.group(2))
				buffer = []
			elif role is not None:
				buffer.append(line)
		flush()
		return messages

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		md_file = self._files.get(conversation_id) or self._index_files().get(conversation_id)
		if md_file is None or not md_file.exists():
			raise FileNotFoundError(f"[{self.name}] Export transcript not found for {conversation_id}")
		return self._parse_transcript(md_file)

	def export_raw(self, conversation_id: str, dest_dir: Path) -> Optional[Path]:
		import shutil

		md_file = self._files.get(conversation_id) or self._index_files().get(conversation_id)
		if md_file is None:
			return None
		dest = dest_dir / "raw.md"  # formato-agnóstico §4.2: el export MD ES el nativo aquí
		shutil.copy2(md_file, dest)
		return dest

	def load_raw(self, raw_file: Path) -> List[Dict[str, Any]]:
		return self._parse_transcript(raw_file)
