"""Fase `consolidation` = HubSynthesisPhase (single-writer).

Sintetiza **hubs de sesión** + **hilo de Ariadna** sobre los engramas curados ya
presentes en Qdrant. La fuente de `work_memories`/`social_memories` es la
**ascensión de Memento**; la ingesta legacy `interaction_memories → work/social`
(drenaje + staging + distill) fue **retirada en v8.0.0 y eliminada**.

`requires_gpu=True`: el runner difiere la fase (señal benigna `vram_busy`) si la
GPU está comprometida, mientras las fases CPU (mantenimiento) siguen corriendo.
"""

from __future__ import annotations

import logging

import red_pill.config as cfg
from red_pill.metabolism.ephemeral_server import EphemeralServer, _check_llm_available
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


def _run_hub_and_thread(memory_manager) -> None:
	"""Síntesis de hubs + micro-hilo de Ariadna sobre los engramas existentes.

	Ambos trazados con sus propios flags (SW_HUBS_ENABLED / SW_THREAD_ENABLED);
	no-op secuencial si están off. `SW_HUBS_MAX_SESSIONS_PER_CYCLE` acota el
	backfill (0 = sin tope); idempotente por `hub_input_hash`.
	"""
	try:
		from red_pill.metabolism.hub_synthesis import synthesize_session_hubs
		from red_pill.metabolism.thread_synthesis import weave_member_threads

		_cap = int(getattr(cfg, "SW_HUBS_MAX_SESSIONS_PER_CYCLE", 0) or 0)
		hub_stats = synthesize_session_hubs(memory_manager, limit_sessions=(_cap or None))
		thread_stats = weave_member_threads(memory_manager)
		if hub_stats.get("enabled") or thread_stats.get("enabled"):
			logger.info(f"[SLEEP ENGINE] Hubs: {hub_stats} · Thread: {thread_stats}")
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Hub/thread synthesis failed: {e}")


class HubSynthesisPhase(SleepPhase):
	"""Fase del sueño: hubs de sesión + hilo de Ariadna (single-writer).

	El `name` = "consolidation" se conserva como stage-id del DAG (G21).
	"""

	@property
	def name(self) -> str:
		return "consolidation"

	@property
	def requires_gpu(self) -> bool:
		return True

	def execute(self, ctx: SleepContext) -> None:
		memory_manager = ctx.memory_manager
		# La síntesis de hubs necesita el LLM; si está caído, se intenta levantar
		# el servidor efímero (best-effort). Si no hay LLM → se difiere al
		# siguiente ciclo (el runner ya difiere por GPU vía requires_gpu).
		if not _check_llm_available():
			logger.warning("[SLEEP ENGINE] Local LLM offline; levantando servidor efímero para hubs.")
			try:
				if not EphemeralServer().start(memory_manager):
					logger.warning("[SLEEP ENGINE] LLM no disponible; hubs/hilo diferidos al próximo ciclo.")
					return
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to start ephemeral server: {e}")
				return
		_run_hub_and_thread(memory_manager)
