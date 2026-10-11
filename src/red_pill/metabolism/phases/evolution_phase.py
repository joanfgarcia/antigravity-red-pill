"""Identity evolution phase: nudge the personality set-point from consolidated memory.

CPU-only (operates on already-stored memories), so it runs regardless of GPU state.
"""

import logging

from red_pill.metabolism.evolution import IdentityEvaluator
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class EvolutionPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "evolution"

	def execute(self, ctx: SleepContext) -> None:
		try:
			IdentityEvaluator.evaluate_set_point(ctx.memory_manager)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Personality evolution failed: {e}")
			return
		# No muta engramas: recalcula el set-point. Se cuenta como 1 evaluación
		# (detalle), no como unidad de engrama.
		ctx.record(self.name, 0, evaluated=1)
