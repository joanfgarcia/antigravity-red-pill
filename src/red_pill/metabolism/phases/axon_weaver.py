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
			"[AXON WEAVER] candidates=%d woven=%d repaired=%d pruned=%d rejected_by_gate=%d W_accepted[min/avg/max]=%s W_rejected[avg]=%s",
			stats["candidates_evaluated"],
			stats["axons_woven"],
			stats["axons_repaired"],
			stats["axons_pruned"],
			stats["rejected_by_gate"],
			f"{min(accepted):.2f}/{sum(accepted) / len(accepted):.2f}/{max(accepted):.2f}" if accepted else "n/a",
			f"{sum(rejected) / len(rejected):.2f}" if rejected else "n/a",
		)

		effective_runs = int(load_axon_state().get("completed_runs", 0))
		if stats["candidates_evaluated"] > 0:
			state = load_axon_state()
			effective_runs = int(state.get("completed_runs", 0)) + 1
			state["completed_runs"] = effective_runs
			state["last_stats"] = {k: v for k, v in stats.items() if not k.startswith("weights_")}
			save_axon_state(state)
			logger.info(f"[AXON WEAVER] Effective run #{effective_runs} recorded (shadow gate P7).")

		try:
			from red_pill.events import AxonWeaveEvent, get_event_bus

			get_event_bus().emit(
				AxonWeaveEvent(
					candidates_evaluated=stats["candidates_evaluated"],
					axons_woven=stats["axons_woven"],
					axons_repaired=stats["axons_repaired"],
					axons_pruned=stats["axons_pruned"],
					rejected_by_gate=stats["rejected_by_gate"],
					w_accepted_avg=round(sum(accepted) / len(accepted), 4) if accepted else None,
					w_rejected_avg=round(sum(rejected) / len(rejected), 4) if rejected else None,
					effective_runs=effective_runs,
				)
			)
		except Exception as e:
			logger.debug(f"[AXON WEAVER] telemetry emit failed: {e}")
