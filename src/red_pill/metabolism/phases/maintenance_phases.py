"""CPU-only maintenance phases: Bayesian hub erosion and RhizoDB washout/pruning.

These need neither LLM nor GPU, so the runner keeps them running even while the
GPU-heavy consolidation phase is deferred (the partial-deferral win of ADR-SLEEP-001).
"""

import logging

from red_pill.metabolism.maintenance import erode_work_hubs, run_rhizodb_washout_and_pruning
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class ErosionPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "erosion"

	def execute(self, ctx: SleepContext) -> None:
		try:
			erode_work_hubs(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run Bayesian hub erosion: {e}")


class WashoutPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "washout"

	def execute(self, ctx: SleepContext) -> None:
		try:
			run_rhizodb_washout_and_pruning(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run RhizoDB washout and pruning: {e}")
