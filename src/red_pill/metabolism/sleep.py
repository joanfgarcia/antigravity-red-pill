"""
Lazarus Sleep Engine — Memory Consolidation Pipeline
=====================================================
Biological sleep cycle for the Red Pill ecosystem. Processes raw interaction
buffers (Qdrant + filesystem staging) through distillation, fixation, hub
synthesis, thread weaving, erosion and identity evolution.

Architecture Decision Record (ADR-SLEEP-001) — 2026-05-31 · DONE 2026-07-16
--------------------------------------------------------------------------
STATUS: Done. The God Class was decomposed once its triggers fired (the file
crossed ~1200 LOC and gained per-phase VRAM gating). `perform_sleep_cycle` is
now a thin, agnostic runner over an ordered SleepPhase pipeline (mirroring the
JanitorPlugin / SentinelPlugin pattern). The tightly-coupled drain loop stays
intact inside ConsolidationPhase, as this ADR warned it must.

	metabolism/
	├── sleep.py                    → agnostic runner (this file) + back-compat re-exports
	├── chunker.py                  → chunk_text, _sanitize_llm_json, _is_template_echo
	├── categorizer.py              → detect_category_heuristics
	├── distiller.py                → distill_engram, synthesize_hub, distill_session_anchors
	├── ephemeral_server.py         → EphemeralServer + _check_llm_available
	├── thread_weaver.py            → thread-state persistence
	├── maintenance.py              → erode_work_hubs, run_rhizodb_washout_and_pruning
	└── phases/                     → SleepPhase contract + the pipeline
		├── base.py                 → SleepPhase (ABC) + SleepContext
		├── consolidation.py        → drain → staging → gamma (requires_gpu)
		├── maintenance_phases.py   → ErosionPhase, WashoutPhase (CPU-only)
		└── evolution_phase.py      → EvolutionPhase (CPU-only)

The payoff of the decomposition: when the GPU is committed to training, the
runner defers only the GPU-heavy consolidation (a benign, non-escalating
vram_busy status signal) while the CPU-only maintenance phases still run —
partial deferral instead of the old all-or-nothing abort.
"""

import logging

from red_pill.events import SleepCompletedEvent, get_event_bus
from red_pill.metabolism.categorizer import detect_category_heuristics
from red_pill.metabolism.chunker import chunk_text
from red_pill.metabolism.distiller import distill_engram, distill_session_anchors, synthesize_hub
from red_pill.metabolism.ephemeral_server import EphemeralServer, _check_llm_available
from red_pill.metabolism.maintenance import erode_work_hubs, run_rhizodb_washout_and_pruning
from red_pill.metabolism.phases import SLEEP_PHASES, SleepContext
from red_pill.metabolism.thread_weaver import _load_thread_state, _save_thread_state

logger = logging.getLogger(__name__)

# Back-compat surface: these moved to focused modules (ADR-SLEEP-001) but stay
# importable from here so existing callers and tests keep working.
__all__ = [
	"EphemeralServer",
	"SLEEP_PHASES",
	"SleepContext",
	"_check_llm_available",
	"_load_thread_state",
	"_save_thread_state",
	"chunk_text",
	"detect_category_heuristics",
	"distill_engram",
	"distill_session_anchors",
	"erode_work_hubs",
	"last_cycle_deferred",
	"perform_sleep_cycle",
	"run_rhizodb_washout_and_pruning",
	"synthesize_hub",
]


def last_cycle_deferred(since: float = 0.0) -> bool:
	"""True si el último ciclo de sueño se auto-difirió (GPU comprometida).

	Lee `sleep_phase_status.json` — el contrato público del sueño hacia fuera
	(el mismo que consulta el runner de jobs). `since` acota la lectura a un
	ciclo concreto: un fichero de una noche anterior no cuenta como deferral.
	"""
	import json

	from red_pill.core.paths import get_state_dir

	try:
		data = json.loads((get_state_dir() / "sleep_phase_status.json").read_text(encoding="utf-8"))
		return bool(data.get("deferred")) and float(data.get("updated_at", 0)) >= since
	except Exception:
		return False


def perform_sleep_cycle(memory_manager, mode: str = "lazy") -> int:
	"""Run one sleep cycle as an agnostic pipeline over the ordered SleepPhases.

	Each phase self-guards; GPU-heavy phases self-defer (setting ctx.deferred and
	emitting a benign vram_busy status signal) when the card is committed to
	training, while CPU-only maintenance phases still run. Returns the number of
	engrams consolidated this cycle.
	"""
	logger.info("=== LAZARUS PULSE: Initiating Synaptic Dreaming (NREM/REM) ===")
	ctx = SleepContext(memory_manager=memory_manager, mode=mode)

	total_phases = len(SLEEP_PHASES)
	for i, phase in enumerate(SLEEP_PHASES):
		try:
			ctx.update_status(phase.name, status="running", phase_index=i + 1, total_phases=total_phases)
			phase.execute(ctx)
			ctx.update_status(phase.name, status="completed", phase_index=i + 1, total_phases=total_phases)
		except Exception as e:
			ctx.update_status(phase.name, status=f"failed: {e}", phase_index=i + 1, total_phases=total_phases)
			logger.error(f"[SLEEP ENGINE] Phase '{phase.name}' failed: {e}")

	ctx.update_status("idle", status="cycle_completed", phase_index=total_phases, total_phases=total_phases)
	logger.info(f"=== LAZARUS PULSE: Sleep Cycle complete. {ctx.total_processed} engrams synaptically woven. ===")
	try:
		from red_pill.core.notifier import SovereignNotifier

		SovereignNotifier.clear_bunker_signal(memory_manager, "local_llm_offline")
		SovereignNotifier.clear_bunker_signal(memory_manager, "ariadne_thread_running")
		# Only clear the deferral alert if consolidation actually ran — i.e. the GPU
		# had headroom. If it self-deferred, vram_busy stays up until a real cycle.
		if not ctx.deferred:
			SovereignNotifier.clear_bunker_signal(memory_manager, "vram_busy")
	except Exception:
		pass

	get_event_bus().emit(SleepCompletedEvent(collection="interaction_memories", processed_count=ctx.total_processed, mode=mode))
	return ctx.total_processed
