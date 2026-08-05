"""ForgeJobDriver — misión Forge completa como job reanudable (control transferible).

Convierte un manifest Forge (plan de fases → pasos con rol+prompt) en un job
de la cola central. Cada step() ejecuta UN paso (un rol) vía el sustrato de
bridges existente (`create_bridge`), escribe su reporte en el workspace
(`.swarm/reports/<rol>-<phase>.json`) y avanza el checkpoint
`{step_index, results[]}`.

CONTROL TRANSFERIBLE (lo nuevo): el checkpoint en BD es la moneda compartida
entre el driver y el main-loop del Orchestrator. Quien tiene el control ejecuta
el siguiente paso:

  - Driver en control (background): el runner recorre el manifest solo.
  - Main-loop toma el control: `job pause` (frontera de paso) → `job status`
    (lee step_index) → ejecuta N pasos inline (misma estructura de reporte,
    mismos schemas) → `job checkpoint <id> {step_index: N}` → el job queda
    PAUSED con el checkpoint actualizado.
  - Main-loop suelta el control: `job resume <id>` → el driver continúa desde
    step_index exactamente donde se quedó.

Manifest, reportes y checkpoint son IDENTICOS en ambos modos: por eso el
handoff es atómico — no hay estado "de la otra mitad".

PATRÓN RFC SLEEP_JOB_DRIVER (aplicado deliberadamente):
  - Checkpoint en BD autoritativo; el fichero público `.swarm/forge_job_status.json`
    es TELECOMETRÍA en vivo (espejo), nunca fuente de resume (auditoría A2 del RFC).
  - `on_fail` por paso: `warn` (default) = marcar y continuar SIN quemar el
    disyuntor (continue-on-error, semántica de unidad del sueño); `stop` =
    RuntimeError → fallo real de job (attempts++, disyuntor si insiste).
  - Un paso fallido con `warn` se registra en `results[]` como FAILED y avanza
    `step_index`; el resto de la misión continúa.
  - Kill/pause cooperativos por unidad: el runner relee estado en frontera (R3);
    un kill marca PAUSED* y la unidad en vuelo completa antes de pausar.
  - `progress` con las claves del renderer del CLI: `current/total/stage_*`
    (el runner añade la EMA de duración por su cuenta).

payload:
	{
		"mission_id": str,                   # aislamiento entre forges (obligatorio)
		"manifest": {                        # el plan Forge
			"workdir": str,                  # workspace de la misión (absoluto)
			"phases": [                      # fases en orden de ejecución
				{
					"id": str,               # ej. "F1"
					"steps": [
						{ "role": "implementor", "agent": "forge-implementor",
						  "prompt": "<FULL role prompt: spec, criteria, context>",
						  "schema"?: "implementor_result",
						  "on_fail"?: "warn" | "stop" }
					]
				}
			]
		},
		"backend"?: "opencode|claude|agy|local",   # default opencode
		"model"?: str, "effort"?: "low|medium|high",
		"timeout"?: int,                           # segundos por paso (default 600)
		"title"?: str,
	}
checkpoint: { "step_index": int, "results": [str, ...] }  # results = resumen por paso
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)


def _flatten_steps(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
	"""Aplana fases→pasos en una lista ordenada de pasos (cada uno con phase_id)."""
	steps: List[Dict[str, Any]] = []
	for phase in manifest.get("phases") or []:
		phase_id = phase.get("id", "?")
		for step in phase.get("steps") or []:
			steps.append({**step, "phase_id": phase_id})
	return steps


class ForgeJobDriver(ResumableJobDriver):
	source = "forge_job"
	min_vram_mb = 0  # backend remoto/CLI; los recursos los gestiona el bridge

	def validate(self, payload: Dict[str, Any]) -> None:
		"""Falla en el SUBMIT, no tres intentos después."""
		if not payload.get("mission_id"):
			raise ValueError("forge_job payload requires 'mission_id' (aislamiento entre forges).")
		manifest = payload.get("manifest")
		if not isinstance(manifest, dict):
			raise ValueError("forge_job payload requires 'manifest'.")
		if not manifest.get("workdir"):
			raise ValueError("forge_job manifest requires 'workdir'.")
		if not _flatten_steps(manifest):
			raise ValueError("forge_job manifest has no phases/steps to run.")
		on_fail_values = {"warn", "stop"}
		for step in _flatten_steps(manifest):
			on_fail = step.get("on_fail", "warn")
			if on_fail not in on_fail_values:
				raise ValueError(f"forge_job step on_fail '{on_fail}' not in {sorted(on_fail_values)}.")

	def preflight(self, payload: Dict[str, Any]) -> None:
		"""Entorno del workspace + bridge disponible → deferral R1, no fallo."""
		from red_pill.swarm.bridges.factory import create_bridge

		workdir = Path(payload["manifest"]["workdir"])
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")
		try:
			bridge = create_bridge(payload.get("backend"))
			if not bridge.health_check():
				raise JobDeferred(f"backend '{payload.get('backend') or 'default'}' not ready")
		except Exception as e:
			raise JobDeferred(f"bridge unavailable: {e}") from e

	def _status_file(self, payload: Dict[str, Any]) -> Path:
		return Path(payload["manifest"]["workdir"]) / ".swarm" / "forge_job_status.json"

	def _write_status(self, payload: Dict[str, Any], data: Dict[str, Any]) -> None:
		"""Telemetría en vivo (espejo del checkpoint en BD). Nunca fuente de resume."""
		try:
			path = self._status_file(payload)
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
		except OSError as e:
			logger.warning(f"[ForgeJob] telemetría no escrita: {e}")

	def _run_role(self, payload: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
		"""Ejecuta UN rol vía bridges y escribe su reporte en el workspace.

		El agente recibe el prompt con la instrucción de emitir su JSON
		conforme al schema en `.swarm/reports/<rol>-<phase>.json`. Devolvemos
		el reporte leído del disco (el archivo es la fuente de verdad que
		comparte el main-loop).
		"""
		from red_pill.swarm.bridges.factory import create_bridge

		workdir = Path(payload["manifest"]["workdir"])
		reports_dir = workdir / ".swarm" / "reports"
		reports_dir.mkdir(parents=True, exist_ok=True)

		role = step.get("role", "step")
		phase_id = step.get("phase_id", "?")
		report_path = reports_dir / f"{role}-{phase_id}.json"

		report_instruction = (
			f"\n\nWrite your report to {report_path} as JSON conforming to your schema "
			f"(role contract). Finish with a one-line summary."
		)
		bridge = create_bridge(payload.get("backend"))
		kwargs: Dict[str, Any] = {"timeout": int(payload.get("timeout", 600))}
		if payload.get("model"):
			kwargs["model"] = payload["model"]
		if payload.get("effort"):
			kwargs["effort"] = payload["effort"]
		result = bridge.prompt(f"{step.get('prompt', '')}\n{report_instruction}", cwd=str(workdir), **kwargs)

		if not result.ok:
			raise RuntimeError(f"forge role '{role}'/{phase_id} failed: {result.error}")

		# El reporte en disco es lo que el main-loop consolida; si el agente no
		# lo escribió, el resumen de la respuesta queda como evidencia mínima.
		if report_path.is_file():
			try:
				return json.loads(report_path.read_text(encoding="utf-8"))
			except json.JSONDecodeError:
				logger.warning(f"[ForgeJob] reporte {report_path} no es JSON válido; se usa resumen.")
		return {"role": role, "phase_id": phase_id, "response_excerpt": (result.response or "")[:2000]}

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		steps = _flatten_steps(payload["manifest"])
		index = int(checkpoint_data.get("step_index", 0))
		results = list(checkpoint_data.get("results", []))
		total = len(steps)

		if index >= total:
			return StepOutcome(completed=True, new_checkpoint=checkpoint_data, summary="forge mission already complete")

		step = steps[index]
		role = step.get("role", "step")
		phase_id = step.get("phase_id", "?")
		on_fail = step.get("on_fail", "warn")

		failed = False
		try:
			report = self._run_role(payload, step)
		except Exception as e:
			failed = True
			report = {"role": role, "phase_id": phase_id, "error": str(e)}
			if on_fail == "stop":
				raise RuntimeError(f"forge role '{role}'/{phase_id} failed with on_fail=stop: {e}") from e
			logger.warning(f"[ForgeJob] {self.short_id} paso {role}/{phase_id} fallido (continue-on-error): {e}")

		results.append(report.get("summary") or f"{role}/{phase_id}: {'FAILED' if failed else 'ok'}")
		new_index = index + 1

		# Telemetría pública (espejo, no autoritativa — auditoría A2 del RFC sleep).
		phase_id_current = step.get("phase_id")
		self._write_status(payload, {
			"mission_id": payload.get("mission_id"),
			"step_index": new_index,
			"total_steps": total,
			"current_role": role,
			"phase_id": phase_id_current,
			"status": "running" if new_index < total else "completed",
			"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
		})

		stage = self._stage_context(steps, index)
		outcome = StepOutcome(
			completed=new_index >= total,
			new_checkpoint={"step_index": new_index, "results": results},
			summary=f"paso {new_index}/{total}: {role}/{phase_id}",
			progress={
				"current": new_index,
				"total": total,
				"percent": round(100 * new_index / total),
				"stage_current": stage["stage_current"],
				"stage_total": stage["stage_total"],
				"stage_label": "fase",
			},
		)
		logger.info(f"[ForgeJob] {self.short_id} step {new_index}/{total} ({role}/{phase_id})")
		return outcome

	@staticmethod
	def _stage_context(steps: List[Dict[str, Any]], index: int) -> Dict[str, int]:
		"""Dimensión 2D fase (como el sueño: unidad X/Y · fase N/M)."""
		phase_ids: List[str] = []
		for s in steps:
			if s.get("phase_id") not in phase_ids:
				phase_ids.append(s.get("phase_id"))
		current_phase = steps[index].get("phase_id") if index < len(steps) else None
		return {
			"stage_current": phase_ids.index(current_phase) + 1 if current_phase in phase_ids else index + 1,
			"stage_total": len(phase_ids),
		}
