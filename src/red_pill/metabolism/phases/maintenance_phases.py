"""CPU-only maintenance phases: Bayesian hub erosion and RhizoDB washout/pruning.

These need neither LLM nor GPU, so the runner keeps them running even while the
GPU-heavy consolidation phase is deferred (the partial-deferral win of ADR-SLEEP-001).
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.forgetting import reap_leafless_branches, run_ladder
from red_pill.metabolism.maintenance import promote_orphan_chunks, run_rhizodb_washout_and_pruning
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
		"""RFC-OLV-001: una sola política de olvido, en este orden.

		Orden: primero la escalera, después el reaper, para que una rama que
		acaba de perder su ultima hoja caiga en la MISMA pasada (C-06).

		`erode_work_hubs` (la erosion bayesiana heredada) ya NO se llama aqui: el
		reaper cubre su caso bueno y su decay borraba ramas auto-contenidas
		(`promoted_from`) que el reaper excluye por definicion. Queda como funcion
		manual/legada, con sus tests, sin participar del ciclo automatico.
		"""
		reaped = purged = frozen = promoted = 0
		mode = str(getattr(cfg, "SW_FORGETTING_LADDER_MODE", "off") or "off").strip().lower()
		if mode not in ("off", "dry_run", "enforce"):
			logger.warning(f"[OLVIDO] Modo de escalera desconocido {mode!r}: se trata como 'off'.")
			mode = "off"

		if mode != "off":
			try:
				ladder = run_ladder(ctx.memory_manager, mode=mode)
				for name, col in (ladder.get("collections") or {}).items():
					purged += int(col.get("applied_delete", 0) or 0)
					frozen += int(col.get("frozen", 0) or 0)
					promoted += int(col.get("promoted", 0) or 0)
					if col.get("planned_delete") or col.get("frozen") or col.get("errors"):
						logger.info(
							f"[OLVIDO] Escalera ({mode}) en {name}: planificado={col.get('planned_delete')} "
							f"aplicado={col.get('applied_delete', 0)} congelado={col.get('frozen')} "
							f"promovido={col.get('promoted')} errores={col.get('errors')}"
						)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to run forgetting ladder: {e}")
			try:
				rep = reap_leafless_branches(ctx.memory_manager, mode=mode)
				reaped = int(rep.get("reaped", 0) or 0)
				if rep.get("candidates"):
					logger.info(f"[OLVIDO] Reaper ({mode}): {rep['candidates']} ramas sin hojas candidatas.")
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to run branch reaper: {e}")

		ctx.record(
			self.name,
			reaped + purged + frozen + promoted,
			reaped=reaped,
			ladder_purga=purged,
			ladder_permastore=frozen,
			ladder_promovidos=promoted,
		)
		if mode != "off":
			logger.info(f"[OLVIDO] Pasada ({mode}): purga={purged} permastore={frozen} promovidos={promoted} reaper={reaped}")


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
