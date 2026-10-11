"""CPU-only maintenance phases: Bayesian hub erosion and RhizoDB washout/pruning.

These need neither LLM nor GPU, so the runner keeps them running even while the
GPU-heavy consolidation phase is deferred (the partial-deferral win of ADR-SLEEP-001).
"""

import logging

from red_pill.metabolism.maintenance import erode_curated, erode_work_hubs, promote_orphan_chunks, run_rhizodb_washout_and_pruning
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class OrphanPromotionPhase(SleepPhase):
	"""Self-healing: hub-less consolidated turns get their newest chunk promoted
	to synthesis_hub so every turn stays reachable by direct recall."""

	@property
	def name(self) -> str:
		return "orphan_promotion"

	def execute(self, ctx: SleepContext) -> None:
		try:
			report = promote_orphan_chunks(ctx.memory_manager) or {}
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run orphan-chunk promotion: {e}")
			return
		promoted = sum(int((r or {}).get("hubless_parents_promoted", 0) or 0) for r in report.values() if isinstance(r, dict))
		flagged = sum(int((r or {}).get("multi_chunk_flagged", 0) or 0) for r in report.values() if isinstance(r, dict))
		ctx.record(self.name, promoted, promoted=promoted, flagged=flagged)


class ErosionPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "erosion"

	def execute(self, ctx: SleepContext) -> None:
		eroded = decayed = demoted = 0
		try:
			stats = erode_work_hubs(ctx.memory_manager) or {}
			eroded = int(stats.get("eroded", 0) or 0)
			decayed = int(stats.get("decayed", 0) or 0)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run Bayesian hub erosion: {e}")
		try:
			curated = erode_curated(ctx.memory_manager)
			if curated.get("enabled"):
				logger.info(f"[SLEEP ENGINE] Curated demote: {curated}")
			demoted = int(curated.get("demoted", 0) or 0)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run curated demote: {e}")
		ctx.record(self.name, eroded + decayed + demoted, eroded=eroded, decayed=decayed, demoted=demoted)


class WashoutPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "washout"

	def execute(self, ctx: SleepContext) -> None:
		try:
			stats = run_rhizodb_washout_and_pruning(ctx.memory_manager) or {}
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run RhizoDB washout and pruning: {e}")
			return
		pruned = int(stats.get("pruned", 0) or 0)
		washed = int(stats.get("washed", 0) or 0)
		ctx.record(self.name, pruned + washed, pruned=pruned, washed=washed)
