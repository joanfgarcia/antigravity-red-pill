"""RevisionPhase (Track R2): batch re-classification during sleep.

Declared GPU-dependent: re-classification is "only" inference, but it hits the
local LLM — the ADR-SLEEP-001 partial-deferral machinery must be able to
postpone it on training nights.
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.phases.base import SleepContext, SleepPhase
from red_pill.metabolism.revision import revise_classifications

logger = logging.getLogger(__name__)


class RevisionPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "revision"

	@property
	def requires_gpu(self) -> bool:
		return True

	def execute(self, ctx: SleepContext) -> None:
		if not cfg.SLEEP_PLUGIN_REVISION:
			logger.debug("[REVISION] Skipped (SLEEP_PLUGIN_REVISION=False)")
			return
		try:
			stats = revise_classifications(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[REVISION] Cycle failed: {e}")
			return
		logger.info(
			"[REVISION] dry_run=%s reviewed=%d confirmed=%d would_move=%d moved=%d hubs_flagged=%d axons_rewired=%d llm_failures=%d",
			stats["dry_run"],
			stats["reviewed"],
			stats["confirmed"],
			stats["would_move"],
			stats["moved"],
			stats["hubs_flagged"],
			stats["axons_rewired"],
			stats["llm_failures"],
		)
