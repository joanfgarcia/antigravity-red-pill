"""Fuente chronicle: conversaciones de Telegram (TelegramSessionManager).

Telegram tiene su propia cascada de sesiones (UUID) y su compactador; se renderiza
a Memento como `telegram:<uuid>` — el `session_id` es el de Telegram. Se excluye a
Telegram del source `opencode` para no duplicar (AD-034/D15).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)


class TelegramSourcePlugin(ChronicleSourcePlugin):
	name = "telegram"
	session_prefix = "telegram:"

	def __init__(self, conv_dir: Optional[Path] = None):
		if conv_dir is None:
			from red_pill.core.paths import get_data_dir

			conv_dir = get_data_dir() / "telegram_conversations"
		self.conv_dir = Path(conv_dir)

	def discover(self) -> List[Tuple[str, int]]:
		if not self.conv_dir.exists():
			return []
		out: List[Tuple[str, int]] = []
		for f in sorted(self.conv_dir.glob("*.json")):
			try:
				d = json.loads(f.read_text(encoding="utf-8"))
			except Exception:
				continue
			steps = d.get("steps") or []
			if steps:
				out.append((str(d.get("id") or f.stem), len(steps)))
		return out

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		f = self.conv_dir / f"{conversation_id}.json"
		if not f.exists():
			return []
		try:
			d = json.loads(f.read_text(encoding="utf-8"))
		except Exception:
			return []
		ts = self._created_at(d)
		out: List[Dict[str, Any]] = []
		for s in d.get("steps") or []:
			text = ((s.get("message") or {}).get("text") or "").strip()
			if not text:
				continue
			role = "user" if "USER" in str(s.get("intent", "")).upper() else "assistant"
			out.append({"role": role, "content": text, "timestamp": ts})
		return out

	@staticmethod
	def _created_at(d: Dict[str, Any]) -> Optional[float]:
		iso = (d.get("summary") or {}).get("createdAt")
		if not iso:
			return None
		try:
			return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
		except Exception:
			return None
