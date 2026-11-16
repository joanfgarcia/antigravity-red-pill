"""CPU-only maintenance phases: Bayesian hub erosion and RhizoDB washout/pruning.

These need neither LLM nor GPU, so the runner keeps them running even while the
GPU-heavy consolidation phase is deferred (the partial-deferral win of ADR-SLEEP-001).
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.forgetting import reap_leafless_branches, run_ladder
from red_pill.metabolism.maintenance import erode_work_hubs, promote_orphan_chunks, run_rhizodb_washout_and_pruning
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
		eroded = decayed = 0
		try:
			stats = erode_work_hubs(ctx.memory_manager) or {}
			eroded = int(stats.get("eroded", 0) or 0)
			decayed = int(stats.get("decayed", 0) or 0)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to run Bayesian hub erosion: {e}")

		# RFC-OLV-001 F3 — la escalera: una sola ruta decide olvidar, en días
		# activos. `off` por defecto; `dry_run` informa sin escribir.
		reaped = ladder_deleted = ladder_frozen = 0
		mode = str(getattr(cfg, "SW_FORGETTING_LADDER_MODE", "off") or "off")
		if mode != "off":
			try:
				rep = reap_leafless_branches(ctx.memory_manager, mode=mode)
				reaped = int(rep.get("reaped", 0) or 0)
				if rep.get("candidates"):
					logger.info(f"[OLVIDO] Reaper ({mode}): {rep['candidates']} ramas sin hojas candidatas.")
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to run branch reaper: {e}")
			try:
				ladder = run_ladder(ctx.memory_manager, mode=mode)
				for name, col in (ladder.get("collections") or {}).items():
					ladder_deleted += int(col.get("deleted", 0) or 0)
					ladder_frozen += int(col.get("frozen", 0) or 0)
					if col.get("deleted") or col.get("frozen"):
						logger.info(f"[OLVIDO] Escalera ({mode}) en {name}: purga={col.get('deleted')} congelado={col.get('frozen')}")
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to run forgetting ladder: {e}")

		ctx.record(
			self.name,
			eroded + decayed + reaped + ladder_deleted + ladder_frozen,
			eroded=eroded,
			decayed=decayed,
			reaped=reaped,
			ladder_purga=ladder_deleted,
			ladder_permastore=ladder_frozen,
		)
		if mode != "off":
			logger.info(f"[OLVIDO] Escalera en modo {mode}: purga={ladder_deleted} permastore={ladder_frozen} reaper={reaped}")


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
