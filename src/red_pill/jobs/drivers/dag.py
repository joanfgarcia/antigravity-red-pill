"""DagJobDriver — composición de etapas en DAG, con fan-out paralelo (RFC_JOB_DAG).

PRIMERA ITERACIÓN (worktree feat/job-dag, 2026-08-06): usa type: agentic|script|subflow.
PENDIENTE DE REFACTOR a la arquitectura v0.5 del RFC (D1-D5 resueltos 2026-08-06):
  · ÁRBOL recursivo: etapa atómica (minion del MinionFactory) O compuesta con
    `sub_etapas`; `parallel: true` es INTENCIÓN declarativa (nivel ≤
    max_parallel_level → paralelo; nivel mayor → secuencial sin error).
  · forge_job/sleep_job pasan a ser RECETAS del DAG (dejan de ser drivers).
  · GPU por etapa: `requires_gpu: true` → el driver aplica el probe de salud
    (nvidia-smi + VRAM + -ngl), genérico y reutilizable (fleco §4.2.1 resuelto).
  · Checkpoint por ruta aplanada (`validators/lens-correctness`) para resume
    determinista a cualquier profundidad.
  · on_fail warn|stop por etapa y sub-etapa (D2); estático al inicio (D3).
Ver RFC_JOB_DAG_PARALLELIZATION.md §1, §2 y §4.

Ejecuta un grafo acíclico de etapas (unidades atómicas) en la cola central.
Cada step() ejecuta el siguiente conjunto de etapas cuyas dependencias están
completas. El checkpoint en BD es autoritativo: `{completed_stage_ids, results}`.
El fan-out (`mode: parallel`) lanza N sub-invocaciones EN HILOS dentro del mismo
step — el runner sigue viendo UN step atómico; el paralelismo vive dentro.

Tipos de etapa:
	agentic — un prompt vía bridge (backend/model/effort)
	script  — un comando externo (subprocess)
	subflow — reutiliza OTRO driver registrado (forge_job, sleep_job, ...)

CONTROL TRANSFERIBLE (heredado de forge_job): el checkpoint del DAG es la
moneda compartida main-loop ↔ driver:
	job_transfer → main-loop ejecuta etapas inline →
	job_checkpoint {completed_stage_ids} → job_resume → el driver continúa.

payload:
	{
		"mission_id": str,
		"manifest": {
			"workdir": str,
			"stages": [
				{
					"id": str,
					"type": "agentic|script|subflow",
					"depends_on"?: [str, ...],       # default: none (arranca)
					"parallel"?: int,                 # fan-out (default 1)
					"on_fail"?: "warn"|"stop",        # default warn (continue-on-error)
					# agentic:
					"backend"?: str, "model"?: str, "effort"?: str, "prompt"?: str,
					# script:
					"command"?: str, "timeout"?: int,
					# subflow:
					"subflow"?: { source: str, payload: dict }
				}
			]
		},
		"max_concurrency"?: int,   # cota global del fan-out (default 4)
		"backend"?: str, "model"?: str, "effort"?: str,   # defaults para agentic
		"timeout"?: int, "title"?: str,
	}
checkpoint: { "completed_stage_ids": [str,...], "results": {id: summary} }
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from red_pill.jobs.drivers.base import JobDeferred, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)

_MAX_PARALLEL_DEFAULT = 4


class DagJobDriver(ResumableJobDriver):
	source = "dag_job"
	min_vram_mb = 0  # los recursos los gestiona cada sub-invocación

	# ── Validación en el submit ───────────────────────────────────────────────
	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		if not payload.get("mission_id"):
			raise ValueError("dag_job payload requires 'mission_id'.")
		manifest = payload.get("manifest")
		if not isinstance(manifest, dict) or not manifest.get("workdir"):
			raise ValueError("dag_job manifest requires 'workdir'.")
		stages = manifest.get("stages")
		if not isinstance(stages, list) or not stages:
			raise ValueError("dag_job manifest requires 'stages' (non-empty).")
		ids: List[str] = []
		for s in stages:
			if not s.get("id"):
				raise ValueError("dag_job stage requires 'id'.")
			if s["id"] in ids:
				raise ValueError(f"dag_job duplicate stage id '{s['id']}'.")
			ids.append(s["id"])
			if s.get("type") not in ("agentic", "script", "subflow"):
				raise ValueError(f"dag_job stage '{s['id']}' type '{s.get('type')}' not in agentic|script|subflow.")
			if s.get("on_fail", "warn") not in ("warn", "stop"):
				raise ValueError(f"dag_job stage '{s['id']}' on_fail not in warn|stop.")
			# dependencias deben referenciar ids existentes
			for dep in s.get("depends_on", []):
				if dep not in ids:
					raise ValueError(f"dag_job stage '{s['id']}' depends_on unknown '{dep}'.")

	# ── Utilidades ────────────────────────────────────────────────────────────
	def _stages(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
		stages = payload["manifest"].get("stages")
		return list(stages) if isinstance(stages, list) else []

	def _stage_by_id(self, payload: Dict[str, Any], stage_id: str) -> Dict[str, Any]:
		for s in self._stages(payload):
			if s.get("id") == stage_id:
				return s
		raise ValueError(f"dag_job stage '{stage_id}' not found")

	def _deps_met(self, stage: Dict[str, Any], completed: List[str]) -> bool:
		return all(d in completed for d in stage.get("depends_on", []))

	def _status_file(self, payload: Dict[str, Any]) -> Path:
		return Path(payload["manifest"]["workdir"]) / ".cell" / "dag_status.json"

	def _write_status(self, payload: Dict[str, Any], data: Dict[str, Any]) -> None:
		try:
			path = self._status_file(payload)
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
		except OSError as e:
			logger.warning(f"[DagJob] telemetría no escrita: {e}")

	def preflight(self, payload: Dict[str, Any]) -> None:
		from red_pill.swarm.bridges.factory import create_bridge

		workdir = Path(payload["manifest"]["workdir"])
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")
		# Al menos un bridge usable para agentic/subflow (fail-open: script puro no lo exige).
		has_agentic = any(s.get("type") in ("agentic", "subflow") for s in self._stages(payload))
		if has_agentic:
			try:
				bridge = create_bridge(payload.get("backend"))
				if not bridge.health_check():
					raise JobDeferred(f"backend '{payload.get('backend') or 'default'}' not ready")
			except Exception as e:
				raise JobDeferred(f"bridge unavailable: {e}") from e

	# ── Ejecución de una etapa ────────────────────────────────────────────────
	def _run_stage(self, payload: Dict[str, Any], stage: Dict[str, Any]) -> str:
		"""Ejecuta UNA etapa y devuelve su resumen (para results[id])."""
		stype = stage["type"]
		if stype == "agentic":
			return self._run_agentic(payload, stage)
		if stype == "script":
			return self._run_script(payload, stage)
		return self._run_subflow(payload, stage)

	def _run_agentic(self, payload: Dict[str, Any], stage: Dict[str, Any]) -> str:
		from red_pill.swarm.bridges.factory import create_bridge

		workdir = Path(payload["manifest"]["workdir"])
		reports_dir = workdir / ".cell" / "reports"
		reports_dir.mkdir(parents=True, exist_ok=True)
		report_path = reports_dir / f"{stage['id']}.json"

		prompt = stage.get("prompt", "")
		report_instruction = (
			f"\n\nWrite your report to {report_path} as JSON conforming to your schema "
			f"(role contract). Finish with a one-line summary."
		)
		bridge = create_bridge(stage.get("backend") or payload.get("backend"))
		kwargs: Dict[str, Any] = {"timeout": int(stage.get("timeout") or payload.get("timeout", 600))}
		if stage.get("model") or payload.get("model"):
			kwargs["model"] = stage.get("model") or payload["model"]
		if stage.get("effort") or payload.get("effort"):
			kwargs["effort"] = stage.get("effort") or payload["effort"]
		result = bridge.prompt(f"{prompt}\n{report_instruction}", cwd=str(workdir), **kwargs)
		if not result.ok:
			raise RuntimeError(f"dag stage '{stage['id']}' failed: {result.error}")
		if report_path.is_file():
			try:
				parsed = json.loads(report_path.read_text(encoding="utf-8"))
				if isinstance(parsed, dict):
					return str(parsed.get("summary") or stage["id"])
			except json.JSONDecodeError:
				pass
		return f"{stage['id']}: ok"

	def _run_script(self, payload: Dict[str, Any], stage: Dict[str, Any]) -> str:
		cmd = stage.get("command")
		if not cmd:
			raise ValueError(f"dag stage '{stage['id']}' type script requires 'command'.")
		r = subprocess.run(cmd, shell=True, cwd=payload["manifest"]["workdir"], capture_output=True, text=True, timeout=int(stage.get("timeout") or payload.get("timeout", 600)))
		if r.returncode != 0:
			raise RuntimeError(f"dag stage '{stage['id']}' script failed rc={r.returncode}: {r.stderr[-300:]}")
		return f"{stage['id']}: ok"

	def _run_subflow(self, payload: Dict[str, Any], stage: Dict[str, Any]) -> str:
		"""Ejecuta un driver anidado (forge_job, sleep_job, ...) vía el registro."""
		from red_pill.jobs.drivers import get_driver

		sub = stage.get("subflow")
		if not isinstance(sub, dict) or not sub.get("source"):
			raise ValueError(f"dag stage '{stage['id']}' type subflow requires subflow.source.")
		sub_payload = dict(sub.get("payload") or {})
		sub_payload.setdefault("mission_id", payload.get("mission_id"))
		driver = get_driver(sub["source"])
		# El subflow es UN paso (delegamos la reanudación interna a su checkpoint).
		outcome = driver.step(sub_payload, {})
		if not outcome.completed:
			# Subflow de varias etapas: anotamos su checkpoint y continuamos en el
			# siguiente step del DAG (se re-anida con checkpoint).
			raise RuntimeError(f"dag subflow '{stage['id']}' ({sub['source']}) not single-step yet")
		return f"{stage['id']}: {outcome.summary or 'ok'}"

	# ── step: ejecutar el siguiente frente de etapas ──────────────────────────
	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		stages = self._stages(payload)
		completed = list(checkpoint_data.get("completed_stage_ids", []))
		results = dict(checkpoint_data.get("results", {}))
		total = len(stages)

		# Frente: etapas no completadas con dependencias satisfechas.
		front = [
			s for s in stages
			if s["id"] not in completed and self._deps_met(s, completed)
		]
		if not front:
			done = len(completed) >= total
			return StepOutcome(
				completed=done,
				new_checkpoint=checkpoint_data,
				summary="dag complete" if done else "waiting on deps (should not happen)",
				progress={"current": len(completed), "total": total, "percent": round(100 * len(completed) / total)},
			)

		# Cota de concurrencia del frente.
		max_conc = int(payload.get("max_concurrency", _MAX_PARALLEL_DEFAULT))
		# Etapas paralelas del frente (parallel > 1) se lanzan juntas; el resto
		# secuencial. Para mantener la atomicidad por step, ejecutamos TODO el
		# frente de una vez (las dependencias ya están satisfechas), limitado
		# por max_concurrency.
		to_run = front[:max_conc]

		new_results = dict(results)
		new_completed = list(completed)

		def _exec_one(stage: Dict[str, Any]) -> "tuple[str, bool]":
			"""Devuelve (summary, failed). El fallo se controla por on_fail."""
			try:
				return self._run_stage(payload, stage), False
			except Exception as e:
				if stage.get("on_fail", "warn") == "stop":
					return str(e), True  # señal para abortar el DAG
				logger.warning(f"[DagJob] {self.short_id} etapa {stage['id']} fallida (warn): {e}")
				return f"{stage['id']}: FAILED ({str(e)[:80]})", False

		with concurrent.futures.ThreadPoolExecutor(max_workers=max_conc) as pool:
			futures = {pool.submit(_exec_one, s): s for s in to_run}
			for fut in concurrent.futures.as_completed(futures):
				stage = futures[fut]
				summary, failed = fut.result()
				if failed:
					# on_fail=stop en una rama → aborta el step (RuntimeError real:
					# el runner lo trata como fallo de job).
					raise RuntimeError(f"dag stage '{stage['id']}' failed with on_fail=stop: {summary}")
				new_results[stage["id"]] = summary
				new_completed.append(stage["id"])

		# Orden estable y determinista (crítico para resume/control transferible):
		# los hilos completan en orden no determinista, pero el checkpoint debe
		# reflejar el orden topológico del manifest.
		stable_order = [s["id"] for s in stages if s["id"] in new_completed]
		new_completed = stable_order

		# Telemetría pública (espejo).
		self._write_status(payload, {
			"mission_id": payload.get("mission_id"),
			"completed": len(new_completed),
			"total": total,
			"status": "running" if len(new_completed) < total else "completed",
			"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
		})

		done = len(new_completed) >= total
		checkpoint = {"completed_stage_ids": new_completed, "results": new_results}
		return StepOutcome(
			completed=done,
			new_checkpoint=checkpoint,
			summary=f"dag {len(new_completed)}/{total} (frente: {', '.join(s['id'] for s in to_run)})",
			progress={"current": len(new_completed), "total": total, "percent": round(100 * len(new_completed) / total)},
		)
