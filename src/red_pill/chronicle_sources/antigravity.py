"""Fuente Antigravity: los JSON desencriptados que exporta el pipeline nocturno."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from red_pill.chronicle_sources.base import ChronicleSourcePlugin

logger = logging.getLogger(__name__)


class AntigravitySourcePlugin(ChronicleSourcePlugin):
	"""Lee `~/.local/share/red-pill/unencrypted_conversations/*.json` (formato cascade)."""

	name = "antigravity"
	session_prefix = ""  # compat: los puntos históricos ya usan el cascade_id desnudo

	def _conversations_dir(self) -> Path:
		from red_pill.core.paths import get_unencrypted_conversations_dir

		return get_unencrypted_conversations_dir()

	def discover(self) -> List[Tuple[str, int]]:
		convo_dir = self._conversations_dir()
		if not convo_dir.exists():
			logger.info(f"[{self.name}] Conversations dir not found: {convo_dir}")
			return []

		discovered = []
		for json_file in sorted(convo_dir.glob("*.json")):
			try:
				data = json.loads(json_file.read_text(encoding="utf-8"))
				discovered.append((json_file.stem, int(data.get("step_count", 0))))
			except Exception as e:
				logger.warning(f"[{self.name}] Could not read {json_file.name}: {e}")
		return discovered

	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		json_file = self._conversations_dir() / f"{conversation_id}.json"
		data = json.loads(json_file.read_text(encoding="utf-8"))
		messages = data.get("messages", [])
		return [{"role": m.get("role"), "content": m.get("content", ""), "timestamp": m.get("timestamp")} for m in messages if isinstance(m, dict)]
