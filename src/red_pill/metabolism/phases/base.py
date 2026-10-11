"""SleepPhase contract + shared SleepContext (ADR-SLEEP-001).

Mirrors the JanitorPlugin / SentinelPlugin pattern already used in the codebase:
an ABC with a name, a config-driven enable switch, and an execute() the agnostic
orchestrator calls. The one addition is `requires_gpu`, which lets the runner defer
GPU-hungry phases while the card is committed to training and still run the rest.
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict

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
	# Producción real por fase (engram-level ops: hubs escritos, chunks promovidos,
	# vacíos purgados, axones tejidos, hubs erosionados/borrados…). Clave = nombre
	# de fase; sub-métricas con `fase.sub` (no se suman al total, son detalle).
	# `total_processed` es la suma de los valores de fase. Sustituye al contador
	# vestigial que la retirada de la ingesta legacy (v8.0.0) dejó clavado en 0.
	metrics: Dict[str, int] = field(default_factory=dict)
	deferred: bool = False  # set by a GPU phase that self-defers (VRAM committed to training)
	# Consolidation drain cutoff (epoch seconds). 0 = unset → the phase captures it
	# at execute() start. The dag_job sleep recipe pins it at job start (first
	# step) so a paused/resumed cycle does not slide the window forward.
	sleep_cutoff_ts: float = 0.0
	# Sonda de pausa a mitad de fase (callable que lanza JobPauseRequested cuando
	# el operador pausa el job dueño mientras un step largo está en vuelo). La
	# inyecta el dag_job (SleepPhaseMinion); las fases
	# pesadas (drenaje de consolidación) la invocan en cada frontera de batch.
	pause_probe: Any = None

	def record(self, phase: str, produced: int = 0, **detail: int) -> None:
		"""Registra la producción real de una fase.

		`produced` = nº de mutaciones sobre engramas (se acumula en `total_processed`
		y en `metrics[phase]`). Los `detail` extra se guardan como `fase.sub`
		(p.ej. `consolidation.hubs`), sin inflar el total: son desglose, no unidades.
		Best-effort: un valor no numérico jamás tumba la fase.
		"""
		try:
			produced = int(produced)
		except (TypeError, ValueError):
			produced = 0
		if produced:
			self.total_processed += produced
		self.metrics[phase] = self.metrics.get(phase, 0) + produced
		for key, value in detail.items():
			try:
				self.metrics[f"{phase}.{key}"] = int(value)
			except (TypeError, ValueError):
				continue

	def update_status(
		self,
		phase_name: str,
		status: str = "running",
		phase_index: int = 0,
		total_phases: int = 8,
		unit: str = "",
		unit_index: int = 0,
		total_units: int = 0,
	) -> None:
		"""Escribe atómicamente el estado de la fase de sueño en tiempo real.

		Campos de unidad (aditivos, telemetría 2D del ciclo como job): el dag_job
		reporta `unit`/`unit_index`/`total_units` además de la fase — el operador
		ve en vivo "unidad 7/14 · fase 5/10". El fichero sigue siendo TELECOMETRÍA
		(espejo), nunca fuente de resume (auditoría A2 del RFC_SLEEP_JOB_DRIVER).
		`status` gana `"deferred"`: honesto cuando un step termina en deferral de
		GPU, y apaga `_nightly_cycle_active` (solo considera "running").
		"""
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
				"metrics": self.metrics,
				"deferred": self.deferred,
				"updated_at": time.time(),
			}
			if unit:
				payload["unit"] = unit
			if unit_index:
				payload["unit_index"] = unit_index
			if total_units:
				payload["total_units"] = total_units
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
