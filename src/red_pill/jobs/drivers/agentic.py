"""AgenticJobDriver — tareas agénticas genéricas por cola (F3b, decisión D1).

Ejecuta un prompt a través del sustrato de bridges existente (swarm/bridges):
el payload define la política (backend/cascada, modelo, effort, cwd) y el
driver solo ejecuta — mismo camino que Telegram/AWAKENINGs. Sustituye al
antiguo swarm/executor.py (que hardcodeaba agy).

payload:
	{
		"prompt": str,                       # la tarea (role prompt incluido)
		"backend"?: "agy|claude|opencode|local|local-tools|pi",
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

		origin = payload.get("origin")
		cascade_spec = payload.get("cascade")
		if cascade_spec:
			from red_pill.config import BridgeTarget

			targets = [BridgeTarget(**t) for t in cascade_spec]
			return create_cascade_bridge(targets, name=f"job:{payload.get('title', 'agentic')}", origin=origin)
		kwargs: Dict[str, Any] = {}
		if origin is not None:
			kwargs["origin"] = origin
		backend_name = str(payload.get("backend") or "").strip().lower()
		if backend_name in ("local-mini", "local_mini"):
			from red_pill.mini.trust import validate_db_path, validate_loopback_url, validate_socket_path, validate_workspace

			for key in ("profile", "continuity_id", "mission_id", "workspace", "db_path", "gpu_socket", "flm_url", "operator", "lineage_id"):
				if payload.get(key) is not None:
					kwargs[key] = payload[key]
			if kwargs.get("workspace") is None and payload.get("cwd"):
				kwargs["workspace"] = payload["cwd"]
			if kwargs.get("workspace") is not None:
				kwargs["workspace"] = validate_workspace(str(kwargs["workspace"]))
			if kwargs.get("db_path") is not None:
				kwargs["db_path"] = validate_db_path(str(kwargs["db_path"]))
			if kwargs.get("gpu_socket") is not None:
				kwargs["gpu_socket"] = validate_socket_path(str(kwargs["gpu_socket"]))
			if kwargs.get("flm_url") is not None:
				kwargs["flm_url"] = validate_loopback_url(str(kwargs["flm_url"]))
			if getattr(self, "job_id", None):
				kwargs["run_ref"] = f"{self.job_id}:{getattr(self, 'attempts', 0)}"
		elif backend_name in ("local-tools", "local_tools"):
			for key in ("continuity_id", "mission_id", "originator", "history_turns", "run_ref"):
				if payload.get(key) is not None:
					kwargs[key] = payload[key]
			if getattr(self, "job_id", None):
				kwargs["run_ref"] = f"{self.job_id}:{getattr(self, 'attempts', 0)}"
		return create_bridge(payload.get("backend"), **kwargs)

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Entorno no disponible (IDE cerrado, SIP caído) → deferral R1, no fallo."""
		try:
			bridge = self._create_bridge(payload)
			healthy = bridge.health_check()
		except ValueError:
			# Configuración inválida (perfil/workspace/ruta/URL): fallo permanente,
			# no un deferral infinito que esconda el error.
			raise
		except Exception as e:
			raise JobDeferred(f"bridge unavailable: {e}") from e
		if not healthy:
			backend = payload.get("backend") or "cascade" if payload.get("cascade") else "default"
			raise JobDeferred(f"backend '{backend}' not ready (health_check failed)")

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		prompt_text = payload.get("prompt")
		if not prompt_text:
			raise ValueError("agentic_job payload requires 'prompt'.")

		job_payload = dict(payload)
		if str(payload.get("backend") or "").strip().lower() in ("local-mini", "local_mini", "local-tools", "local_tools"):
			if not job_payload.get("continuity_id"):
				job_payload["continuity_id"] = checkpoint_data.get("continuity_id")
		bridge = self._create_bridge(job_payload)
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

		checkpoint: Dict[str, Any] = {"response": (result.response or "")[:4000], "conversation_id": result.conversation_id}
		continuity = getattr(bridge, "continuity_id", None)
		if continuity:
			checkpoint["continuity_id"] = continuity
		return StepOutcome(
			completed=True,
			new_checkpoint=checkpoint,
			summary=(result.response or "")[:280],
			progress={"current_step": 1, "total_steps": 1, "percent": 100},
		)
