"""Sleep-cycle phases: the agnostic pipeline the orchestrator discovers and runs.

Per ADR-SLEEP-001 (DONE): perform_sleep_cycle became a thin, agnostic runner over
ordered SleepPhase plugins. Each phase declares requires_gpu; the runner defers the
GPU-hungry phases when the card is committed (training) while still running the
CPU-only maintenance phases — partial deferral instead of an all-or-nothing abort.
"""

from red_pill.metabolism.phases.axon_weaver import AxonWeaverPhase
from red_pill.metabolism.phases.base import SleepContext, SleepPhase
from red_pill.metabolism.phases.consolidation import ConsolidationPhase
from red_pill.metabolism.phases.evolution_phase import EvolutionPhase
from red_pill.metabolism.phases.hygiene_phase import HygienePhase
from red_pill.metabolism.phases.maintenance_phases import ErosionPhase, OrphanPromotionPhase, WashoutPhase
from red_pill.metabolism.phases.operator_profile_phase import OperatorProfilePhase
from red_pill.metabolism.phases.recent_activity_phase import RecentActivityPhase
from red_pill.metabolism.phases.revision_phase import RevisionPhase

# Ordered pipeline. GPU-heavy consolidation first (drain → staging → gamma),
# then CPU-only housekeeping that runs even while consolidation is deferred.
# OrphanPromotion rescues hub-less turns right after consolidation so the
# weaver and erosion see them as first-class hubs the same cycle. AxonWeaver
# runs after consolidation (tonight's engrams are weavable) and before
# erosion (ADR-AXON-001 §5).
SLEEP_PHASES: list[SleepPhase] = [
	ConsolidationPhase(),
	OrphanPromotionPhase(),
	HygienePhase(),
	AxonWeaverPhase(),
	ErosionPhase(),
	WashoutPhase(),
	RevisionPhase(),
	EvolutionPhase(),
	OperatorProfilePhase(),
	RecentActivityPhase(),
]

__all__ = [
	"SLEEP_PHASES",
	"AxonWeaverPhase",
	"ConsolidationPhase",
	"ErosionPhase",
	"EvolutionPhase",
	"HygienePhase",
	"OrphanPromotionPhase",
	"RevisionPhase",
	"SleepContext",
	"SleepPhase",
	"WashoutPhase",
]
