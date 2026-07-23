"""AgenticJobDriver — tareas agénticas genéricas por cola (F3b, decisión D1).

Ejecuta un prompt a través del sustrato de bridges existente (swarm/bridges):
el payload define la política (backend/cascada, modelo, effort, cwd) y el
driver solo ejecuta — mismo camino que Telegram/AWAKENINGs. Sustituye al
antiguo swarm/executor.py (que hardcodeaba agy).

payload:
	{
		"prompt": str,                       # la tarea (role prompt incluido)
		"backend"?: "agy|claude|opencode|local|local-tools",
		"cascade"?: [{backend, model, effort}, ...],  # → CascadeBridge
		"model"?: str, "effort"?: "low|medium|high",
		"cwd"?: str, "timeout"?: int, "title"?: str,
	}
checkpoint: { "response"?: str, "conversation_id"?: str }
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


class AgenticJobDriver(ResumableJobDriver):
	source = "agentic_job"
	min_vram_mb = 0  # los recursos se comprueban en preflight según el backend del payload

	def _create_bridge(self, payload: Dict[str, Any]):
		from red_pill.swarm.bridges.factory import create_bridge, create_cascade_bridge

		cascade_spec = payload.get("cascade")
		if cascade_spec:
			from red_pill.config import BridgeTarget

			targets = [BridgeTarget(**t) for t in cascade_spec]
			return create_cascade_bridge(targets, name=f"job:{payload.get('title', 'agentic')}")
		return create_bridge(payload.get("backend"))

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Entorno no disponible (IDE cerrado, SIP caído) → deferral R1, no fallo."""
		try:
			bridge = self._create_bridge(payload)
			healthy = bridge.health_check()
		except Exception as e:
			raise JobDeferred(f"bridge unavailable: {e}") from e
		if not healthy:
			backend = payload.get("backend") or "cascade" if payload.get("cascade") else "default"
			raise JobDeferred(f"backend '{backend}' not ready (health_check failed)")

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		prompt_text = payload.get("prompt")
		if not prompt_text:
			raise ValueError("agentic_job payload requires 'prompt'.")

		bridge = self._create_bridge(payload)
		kwargs: Dict[str, Any] = {"timeout": int(payload.get("timeout", 600))}
		if payload.get("model"):
			kwargs["model"] = payload["model"]
		if payload.get("effort"):
			kwargs["effort"] = payload["effort"]
		if payload.get("cwd"):
			kwargs["cwd"] = payload["cwd"]

		result = bridge.prompt(prompt_text, **kwargs)
		if not result.ok:
			raise RuntimeError(f"agentic task failed: {result.error}")

		return StepOutcome(
			completed=True,
			new_checkpoint={"response": (result.response or "")[:4000], "conversation_id": result.conversation_id},
			summary=(result.response or "")[:280],
			progress={"current_step": 1, "total_steps": 1, "percent": 100},
		)
