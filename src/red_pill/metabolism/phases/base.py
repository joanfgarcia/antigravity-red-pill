"""SleepPhase contract + shared SleepContext (ADR-SLEEP-001).

Mirrors the JanitorPlugin / SentinelPlugin pattern already used in the codebase:
an ABC with a name, a config-driven enable switch, and an execute() the agnostic
orchestrator calls. The one addition is `requires_gpu`, which lets the runner defer
GPU-hungry phases while the card is committed to training and still run the rest.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


import json
import logging
import os
import time

logger = logging.getLogger(__name__)


@dataclass
class SleepContext:
	"""Mutable state shared across phases of a single sleep cycle.

	The tightly-coupled drain state (chunks, hubs, thread weaving, failed ids) stays
	local to ConsolidationPhase, as ADR-SLEEP-001 warns. Only what genuinely crosses
	the phase boundary lives here.
	"""

	memory_manager: Any
	mode: str = "lazy"
	total_processed: int = 0
	deferred: bool = False  # set by a GPU phase that self-defers (VRAM committed to training)

	def update_status(self, phase_name: str, status: str = "running", phase_index: int = 0, total_phases: int = 8) -> None:
		"""Escribe atómicamente el estado de la fase de sueño en tiempo real."""
		try:
			from red_pill.core.paths import get_state_dir

			state_dir = get_state_dir()
			os.makedirs(state_dir, exist_ok=True)
			status_file = state_dir / "sleep_phase_status.json"
			payload = {
				"active_phase": phase_name,
				"status": status,
				"phase_index": phase_index,
				"total_phases": total_phases,
				"total_processed": self.total_processed,
				"deferred": self.deferred,
				"updated_at": time.time(),
			}
			tmp_file = state_dir / "sleep_phase_status.json.tmp"
			with open(tmp_file, "w", encoding="utf-8") as f:
				json.dump(payload, f, indent=2)
			os.replace(tmp_file, status_file)
		except Exception as e:
			logger.warning(f"[SLEEP-CONTEXT] Failed to write phase status: {e}")


class SleepPhase(ABC):
	"""A discrete stage of the sleep cycle the orchestrator discovers and runs."""

	@property
	@abstractmethod
	def name(self) -> str:
		"""Human-readable phase name (e.g. 'consolidation', 'erosion')."""

	@property
	def requires_gpu(self) -> bool:
		"""True if the phase needs the local LLM/GPU; the runner defers it when the
		card is committed to training. CPU-only phases (default) always run."""
		return False

	def is_enabled(self, config_dict: dict) -> bool:
		"""Enabled unless config disables it by name (mirrors JanitorPlugin)."""
		plugin_cfg = config_dict.get("sleep_phases", {}).get(self.name, {})
		if isinstance(plugin_cfg, dict):
			return bool(plugin_cfg.get("enabled", True))
		return bool(plugin_cfg) if plugin_cfg != {} else True

	@abstractmethod
	def execute(self, ctx: SleepContext) -> None:
		"""Run the phase, reading and mutating the shared context in place."""
