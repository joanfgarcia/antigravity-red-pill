import asyncio
import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.mystique import mystique_engine

logger = logging.getLogger(__name__)


class MystiquePlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Mystique Protocol (Dynamic Personality)"

	@property
	def timeout(self) -> float:
		return 1.0  # Very fast deterministic logic

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "INTERCEPTOR_ENABLED", False)

	async def execute(self, prompt: str) -> str:
		try:
			# Suggest a skin based on current mood (USP)
			# We use to_thread because mystique_engine might do I/O or heavy math
			suggestion = await asyncio.to_thread(mystique_engine.suggest_skin, strategy="affinity", context="work")

			name = suggestion.get("name", "standard").upper()
			data = suggestion.get("data", {})
			personality = data.get("personality", "Professional and efficient.")
			chroma = data.get("chroma", "gray")

			lines = [
				"=== DYNAMIC PERSONALITY (MYSTIQUE PROTOCOL) ===",
				f"ACTIVED Lore Skin: {name} [{chroma}]",
				f"Persona Anchor: {personality}",
				"---",
			]

			return "\n".join(lines)
		except Exception as e:
			logger.error(f"Mystique Plugin crashed: {e}")
			return ""
