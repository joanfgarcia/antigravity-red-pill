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

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


class AgenticJobDriver(ResumableJobDriver):
	source = "agentic_job"
	min_vram_mb = 0  # los recursos se comprueban en preflight según el backend del payload

	def _create_bridge(self, payload: Dict[str, Any]):
		from red_pill.swarm.bridges.factory import create_bridge, create_cascade_bridge

		origin = payload.get("origin")
		identity: Dict[str, Any] = {}
		if payload.get("continuity_id"):
			identity = {
				"continuity_id": payload.get("continuity_id"),
				"mission_id": payload.get("parent_mission_id") or payload.get("mission_id"),
				"parent_mission_id": payload.get("parent_mission_id"),
				"originator": payload.get("originator") or (f"job:{self.job_id}" if getattr(self, "job_id", None) else None),
				"role": payload.get("role") or "job",
				"job_id": getattr(self, "job_id", None),
			}
		cascade_spec = payload.get("cascade")
		if cascade_spec:
			from red_pill.config import BridgeTarget

			targets = [BridgeTarget(**t) for t in cascade_spec]
			return create_cascade_bridge(
				targets,
				name=f"job:{payload.get('title', 'agentic')}",
				origin=origin,
				**{key: value for key, value in identity.items() if value},
			)
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
			for key in ("continuity_id", "mission_id", "originator", "history_turns", "run_ref", "context_tokens"):
				if payload.get(key) is not None:
					kwargs[key] = payload[key]
			if getattr(self, "job_id", None):
				kwargs["run_ref"] = f"{self.job_id}:{getattr(self, 'attempts', 0)}"
		else:
			kwargs.update({key: value for key, value in identity.items() if value})
		return create_bridge(payload.get("backend"), **kwargs)

	def _request_id(self) -> str:
		return f"{self.job_id or 'unbound'}:{self.attempts}"

	def begin_step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> Dict[str, Any]:
		"""B-01j: persiste la intención del turno ANTES de invocar al bridge.

		Funciona para cualquier backend (cloud/local/cascade). El runner llama a
		este hook y guarda el checkpoint; si el proceso muere después, el trabajo
		pendiente queda visible en `job status`.
		"""
		checkpoint = dict(checkpoint_data or {})
		request_id = self._request_id()
		old = checkpoint.get("pending_turn") if isinstance(checkpoint.get("pending_turn"), dict) else None
		if old and old.get("request_id") == request_id and old.get("status") == "completed":
			return checkpoint
		prompt = str(payload.get("prompt") or "")
		backend = str(payload.get("backend") or ("cascade" if payload.get("cascade") else "")).strip()
		model = str(payload.get("model") or "").strip()
		resume_count = 0
		started_at = time.time()
		if old and old.get("request_id") == request_id:
			resume_count = int(old.get("resume_count") or 0) + 1
			if old.get("status") == "pending":
				started_at = float(old.get("started_at") or started_at)
		checkpoint["request_id"] = request_id
		checkpoint["pending_turn"] = {
			"request_id": request_id,
			"status": "pending",
			"job_id": self.job_id or "",
			"attempt": int(self.attempts or 0),
			"backend": backend,
			"model": model,
			"prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
			"prompt_preview": prompt[:500],
			"started_at": started_at,
			"resume_count": resume_count,
		}
		return checkpoint

	def abort_step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any], reason: str) -> Dict[str, Any]:
		"""Marca el turno pendiente como abortado (timeout, error o kill)."""
		checkpoint = dict(checkpoint_data or {})
		request_id = str(checkpoint.get("request_id") or self._request_id())
		pending = dict(checkpoint.get("pending_turn") or {})
		if pending.get("status") == "completed":
			return checkpoint
		pending.update(
			request_id=request_id,
			status="aborted",
			reason=str(reason or "aborted")[:500],
			aborted_at=time.time(),
		)
		checkpoint["request_id"] = request_id
		checkpoint["pending_turn"] = pending
		return checkpoint

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Entorno no disponible (IDE cerrado, SIP caído) → deferral R1, no fallo."""
		# Un cwd efímero (/tmp) puede desaparecer en un reinicio; un job reanudable
		# debe fallar claro, no arrancar el hijo en otro workspace. Solo se valida
		# si el payload lo declara: sin cwd, el bridge usa su default persistente.
		cwd = str(payload.get("cwd") or "").strip()
		if cwd and not Path(cwd).is_dir():
			raise ValueError(
				f"agentic_job cwd no existe o no es un directorio: {cwd}. "
				"Para jobs reanudables usa un workspace persistente (no /tmp)."
			)
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

		checkpoint = dict(checkpoint_data or {})
		request_id = str(checkpoint.get("request_id") or self._request_id())
		pending = checkpoint.get("pending_turn") if isinstance(checkpoint.get("pending_turn"), dict) else None
		if not pending or pending.get("request_id") != request_id:
			checkpoint = self.begin_step(payload, checkpoint)
			request_id = str(checkpoint.get("request_id") or request_id)
			pending = checkpoint.get("pending_turn") if isinstance(checkpoint.get("pending_turn"), dict) else None
		if pending and pending.get("status") == "completed":
			response = str(pending.get("response") or checkpoint.get("response") or "")
			return StepOutcome(
				completed=True,
				new_checkpoint=checkpoint,
				summary=response[:280],
				progress={"current_step": 1, "total_steps": 1, "percent": 100},
			)

		job_payload = dict(payload)
		if str(payload.get("backend") or "").strip().lower() in ("local-mini", "local_mini", "local-tools", "local_tools"):
			if not job_payload.get("continuity_id"):
				job_payload["continuity_id"] = checkpoint.get("continuity_id")
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

		response = (result.response or "")[:4000]
		pending = dict(checkpoint.get("pending_turn") or {})
		pending.update(
			request_id=request_id,
			status="completed",
			response=response,
			conversation_id=result.conversation_id,
			completed_at=time.time(),
		)
		checkpoint["pending_turn"] = pending
		checkpoint["request_id"] = request_id
		checkpoint["response"] = response
		checkpoint["conversation_id"] = result.conversation_id
		continuity = getattr(bridge, "continuity_id", None)
		if continuity:
			checkpoint["continuity_id"] = continuity
		return StepOutcome(
			completed=True,
			new_checkpoint=checkpoint,
			summary=response[:280],
			progress={"current_step": 1, "total_steps": 1, "percent": 100},
		)
