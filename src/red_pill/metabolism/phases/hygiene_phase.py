"""HygienePhase: purge empty engrams (zero recall value, real graph cost).

CPU-only. Runs after OrphanPromotion (a hub-less parent's chunk gets promoted
BEFORE hygiene judges the family) and before the AxonWeaver (never weave
what is about to vanish). Chain-restitching semantics in purge_empty_engrams.
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.maintenance import purge_empty_engrams
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class HygienePhase(SleepPhase):
	@property
	def name(self) -> str:
		return "hygiene"

	def execute(self, ctx: SleepContext) -> None:
		if not cfg.SLEEP_PLUGIN_HYGIENE:
			logger.debug("[HYGIENE] Skipped (SLEEP_PLUGIN_HYGIENE=False)")
			return
		try:
			purge_empty_engrams(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[HYGIENE] Failed to run empty-engram purge: {e}")
