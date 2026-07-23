"""FlowJobDriver — driver piloto del Centralized Job Manager (F3).

Convierte un flow YAML existente (FlowEngine + GruOrchestrator) en un job
pausable, reanudable y persistente: checkpoint = índice de la etapa del flow.
Cada step() ejecuta UNA etapa (un minion) respetando su `on_fail`.

payload: { "flow_id": str, "title"?: str, "kwargs"?: dict }
checkpoint: { "step_index": int, "results": [str, ...] }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from red_pill.jobs.drivers.base import ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


class FlowJobDriver(ResumableJobDriver):
	source = "flow_job"
	min_vram_mb = 0  # el routing VRAM por minion ya lo hace SwarmScheduler (ngl)

	def __init__(self):
		self._orchestrator = None

	def _get_orchestrator(self):
		"""Instancia perezosa y cacheada: un GruOrchestrator por job, no por step."""
		if self._orchestrator is None:
			from red_pill.swarm.orchestrator import GruOrchestrator

			self._orchestrator = GruOrchestrator()
		return self._orchestrator

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		flow_id = payload.get("flow_id")
		if not flow_id:
			raise ValueError("flow_job payload requires 'flow_id'.")

		orchestrator = self._get_orchestrator()
		flow = orchestrator.flow_engine.get_flow(flow_id, orchestrator.workspace_root)
		if not flow:
			raise ValueError(f"Flow '{flow_id}' not found in registry.")

		steps = flow.get("steps", [])
		index = checkpoint_data.get("step_index", 0)
		results = list(checkpoint_data.get("results", []))
		total = len(steps)

		if index >= total:
			return StepOutcome(completed=True, new_checkpoint=checkpoint_data, summary=f"flow '{flow_id}' already complete")

		flow_step = steps[index]
		minion_id = flow_step.get("minion")
		on_fail = flow_step.get("on_fail", "warn")

		# trace=False: el SAS por etapa sería ruido — el reporte final lo emite el runner.
		step_results = asyncio.run(
			orchestrator.deploy_swarm(
				task=f"Flow Step: {minion_id}",
				minions=[minion_id],
				trace=False,
				**payload.get("kwargs", {}),
			)
		)

		failed = any(r.status == "failed" for r in step_results)
		results.append(f"{minion_id}: {'failed' if failed else 'success'}")

		if failed and on_fail in ("stop", "abort"):
			# Fallo real del job: el runner lo pasa por mark_failed (attempts+1);
			# el checkpoint conserva la etapa para reintentar desde aquí.
			raise RuntimeError(f"Flow '{flow_id}' stopped at step {index} ({minion_id}): on_fail={on_fail}")

		new_checkpoint = {"step_index": index + 1, "results": results}
		done = index + 1 >= total
		return StepOutcome(
			completed=done,
			new_checkpoint=new_checkpoint,
			summary="; ".join(results) if done else f"step {index + 1}/{total} ({minion_id})",
			progress={"current_step": index + 1, "total_steps": total, "percent": round(100 * (index + 1) / total)},
		)
