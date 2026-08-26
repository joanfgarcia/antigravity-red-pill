"""Fuente memory_queue (RFC-002 MUST 10): turnos sin provider store propio.

Las superficies que solo capturan vía MCP `memorize_interaction` (Telegram,
AWAKENINGs, legacy) no tienen store nativo — la cola ES su registro canónico.
Se agrupan por `originator` + día: `mcp:<originator>:<AAAA-MM-DD>`. Los
originators cubiertos por otras fuentes (antigravity/claude_code/opencode)
se excluyen: su verbatim ya entra por el provider store.

No está en CHRONICLE_ARCHIVE_SOURCES (el archivo Qdrant no cambia, MUST 8);
Memento la habilita vía MEMENTO_EXTRA_SOURCES.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)

UNKNOWN_ORIGINATOR = "unknown"


class MemoryQueueSourcePlugin(ChronicleSourcePlugin):
	"""Agrupa filas de bunker_queue.db (tabla memory_queue) en pseudo-sesiones por originator+día."""

	name = "memory_queue"
	session_prefix = "mcp:"

	def __init__(self, db_path: Optional[Path] = None):
		if db_path is None:
			from red_pill.core.paths import get_queue_dir

			db_path = get_queue_dir() / "bunker_queue.db"
		self.db_path = Path(db_path)

	def _connect(self) -> sqlite3.Connection:
		return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

	def _excluded_originators(self) -> List[str]:
		import red_pill.config as cfg

		return list(getattr(cfg, "CHRONICLE_ARCHIVE_SOURCES", ["antigravity", "claude_code", "opencode"]))

	def _where_group(self, originator: str) -> Tuple[str, List[Any]]:
		if originator == UNKNOWN_ORIGINATOR:
			return "originator IS NULL", []
		return "originator = ?", [originator]

	def discover(self) -> List[Tuple[str, int]]:
		if not self.db_path.exists():
			logger.info(f"[{self.name}] Queue database not found: {self.db_path}")
			return []
		excluded = self._excluded_originators()
		placeholders = ",".join("?" for _ in excluded)
		try:
			con = self._connect()
			try:
				rows = con.execute(
					f"SELECT COALESCE(originator, '{UNKNOWN_ORIGINATOR}'), date(created_at, 'unixepoch'), COUNT(*) "
					f"FROM memory_queue WHERE originator IS NULL OR originator NOT IN ({placeholders}) "
					"GROUP BY 1, 2 ORDER BY 2, 1",
					excluded,
				).fetchall()
			finally:
				con.close()
		except sqlite3.Error as e:
			logger.warning(f"[{self.name}] Could not read queue database: {e}")
			return []
		return [(f"{originator}:{day}", int(count)) for originator, day, count in rows if day]

	def _rows_of(self, conversation_id: str) -> List[Tuple[Any, ...]]:
		originator, _, day = conversation_id.rpartition(":")
		where, params = self._where_group(originator)
		con = self._connect()
		try:
			return con.execute(
				f"SELECT prompt, response, created_at FROM memory_queue WHERE ({where}) AND date(created_at, 'unixepoch') = ? "
				"ORDER BY created_at, id",
				params + [day],
			).fetchall()
		finally:
			con.close()

	def _normalize_rows(self, rows: List[Tuple[Any, ...]]) -> List[Dict[str, Any]]:
		messages: List[Dict[str, Any]] = []
		for prompt, response, created_at in rows:
			if prompt and str(prompt).strip():
				messages.append({"role": "user", "content": str(prompt), "timestamp": created_at})
			if response and str(response).strip():
				messages.append({"role": "assistant", "content": str(response), "timestamp": created_at})
		return messages

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		return self._normalize_rows(self._rows_of(conversation_id))

	def export_raw(self, conversation_id: str, dest_dir: Path) -> Optional[Path]:
		rows = self._rows_of(conversation_id)
		if not rows:
			return None
		dest = dest_dir / "raw.json"
		dest.write_text(json.dumps({"group": conversation_id, "rows": [list(r) for r in rows]}, ensure_ascii=False), encoding="utf-8")
		return dest

	def load_raw(self, raw_file: Path) -> List[Dict[str, Any]]:
		data = json.loads(raw_file.read_text(encoding="utf-8"))
		return self._normalize_rows([tuple(r) for r in data.get("rows", [])])
