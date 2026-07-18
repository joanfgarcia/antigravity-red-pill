"""AxonWeaverPhase (ADR-AXON-001): CPU-only cross-collection weaving.

Runs after consolidation (fresh engrams from tonight are weavable) and before
erosion. Counts *effective* runs — completed without error AND with >0
candidates evaluated — into persistent state; the shadow-rollout gate (P7)
reads that counter, so nights where the laptop slept or the window was empty
don't count toward enabling the read-path.
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.axons import load_axon_state, save_axon_state, weave_cross_axons
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class AxonWeaverPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "axon_weaver"

	def execute(self, ctx: SleepContext) -> None:
		if not cfg.SLEEP_PLUGIN_AXONS:
			logger.debug("[AXON WEAVER] Skipped (SLEEP_PLUGIN_AXONS=False)")
			return
		try:
			stats = weave_cross_axons(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[AXON WEAVER] Weaving cycle failed: {e}")
			return

		accepted = stats.get("weights_accepted", [])
		rejected = stats.get("weights_rejected", [])
		logger.info(
			"[AXON WEAVER] candidates=%d woven=%d repaired=%d pruned=%d rejected_by_gate=%d "
			"W_accepted[min/avg/max]=%s W_rejected[avg]=%s",
			stats["candidates_evaluated"],
			stats["axons_woven"],
			stats["axons_repaired"],
			stats["axons_pruned"],
			stats["rejected_by_gate"],
			f"{min(accepted):.2f}/{sum(accepted) / len(accepted):.2f}/{max(accepted):.2f}" if accepted else "n/a",
			f"{sum(rejected) / len(rejected):.2f}" if rejected else "n/a",
		)

		if stats["candidates_evaluated"] > 0:
			state = load_axon_state()
			state["completed_runs"] = int(state.get("completed_runs", 0)) + 1
			state["last_stats"] = {k: v for k, v in stats.items() if not k.startswith("weights_")}
			save_axon_state(state)
			logger.info(f"[AXON WEAVER] Effective run #{state['completed_runs']} recorded (shadow gate P7).")
