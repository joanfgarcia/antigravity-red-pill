"""
Chronicle Extractor Plugin for the Antigravity IDE (gRPC).
"""

from __future__ import annotations

import logging

from red_pill.metabolism.chronicle.base import ChronicleExtractorPlugin
from red_pill.metabolism.ls_snatcher import snatch_all_trajectories

logger = logging.getLogger(__name__)


class AntigravityExtractorPlugin(ChronicleExtractorPlugin):
	"""Extractor plugin that snatches active trajectories from the Antigravity IDE."""

	def extract(self) -> int:
		logger.info("[Antigravity Plugin] Starting trajectory extraction...")
		try:
			count = snatch_all_trajectories()
			logger.info(f"[Antigravity Plugin] Snatching complete. Staged {count} trajectories.")
			return count
		except Exception as e:
			logger.error(f"[Antigravity Plugin] Snatching failed: {e}")
			return 0
