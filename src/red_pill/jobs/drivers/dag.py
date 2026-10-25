"""DagJobDriver — resumable job driver for a DAG manifest (RFC-JOB_DAG).

This module is the thin spine of the DAG driver. The heavy lifting lives in
cohesive modules, and each is mixin-composed so the call sites stay unchanged:

- `dag_manifest.py`: pure tree helpers + type/ceiling constants.
- `dag_types/`: the stage-type REGISTRY (agent/command/compound/dag); one module
per node type (adding a node = write its module and register it).
- `dag_validate.py`: payload/tree validation (dispatched via the registry).
- `dag_compose.py`: `type: dag` composition-by-reference expansion.
- `dag_fanout.py`: fan-out-by-items expansion + the parallel pause gate.
- `dag_exec.py`: atomic-stage execution (GPU probe, timeout/budget, minion).
- `dag_schedule.py`: step scheduling (front, parallel groups, pause, progress).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from red_pill.jobs.drivers.base import ResumableJobDriver
from red_pill.jobs.drivers.dag_exec import DagExecMixin, _gpu_health_probe  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_fanout import DagFanoutMixin, _GroupPauseGate  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_manifest import _resolve_minion_kind, _resolve_on_fail  # noqa: F401  (re-exported: tests)
from red_pill.jobs.drivers.dag_schedule import DagScheduleMixin

logger = logging.getLogger(__name__)


class DagJobDriver(DagScheduleMixin, DagExecMixin, DagFanoutMixin, ResumableJobDriver):
	source = "dag_job"
	min_vram_mb = 0  # los recursos se gestionan por etapa en preflight (GPU probe)

	# Marca de inicio del step en curso (monotónica) — base de la cota de tiempo.
	_step_started: Optional[float] = None

	# ── Validación en el submit (recursiva sobre el árbol) ─────────────────────
	@classmethod
	def _load_recipe(cls, reference: str) -> Tuple[str, Dict[str, Any], int, Optional[str], bool]:
		"""Resuelve una receta con el MISMO mecanismo del CLI (RECIPE_DIRS).

		Indirección inyectable: `validate`/`expand_manifest` pasan `cls._load_recipe`
		a sus módulos, así un test (o un backend alternativo) sustituye la resolución
		de recetas sin tocar la lógica de validación/composición.
		"""
		from red_pill.jobs.recipes import load_recipe

		return load_recipe(reference, base_dir=None)

	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		from red_pill.jobs.drivers.dag_validate import validate_payload

		validate_payload(payload, cls._load_recipe)

	@classmethod
	def expand_manifest(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
		"""Aplana las etapas `type: dag` a `compound` (RFC_JOB_DAG §4.5).

		Se llama en el SUBMIT (CLI/MCP) tras validate: el job se persiste con el
		árbol ya expandido, de modo que step()/checkpoint/resume trabajan SIEMPRE
		sobre compounds y hojas — el determinismo del resume no depende de que la
		receta siga igual en disco. Devuelve un payload nuevo (sin mutar el original).
		"""
		from red_pill.jobs.drivers.dag_compose import expand_manifest

		return expand_manifest(payload, cls._load_recipe)

	def begin_step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> Dict[str, Any]:
		"""RFC-INTEROP-003 S2: registra el leg `dag:<job_id>` si hay alma."""
		checkpoint = super().begin_step(payload, checkpoint_data)
		continuity = checkpoint.get("continuity_id") or payload.get("continuity_id")
		if not continuity or not getattr(self, "job_id", None):
			return checkpoint
		trusted = os.getenv("REDPILL_CONTINUITY_ID")
		if trusted and str(continuity) != str(trusted):
			raise ValueError("dag_job continuity_id no coincide con REDPILL_CONTINUITY_ID")
		mission = str(checkpoint.get("parent_mission_id") or payload.get("parent_mission_id") or payload.get("mission_id") or "")
		try:
			from red_pill.core.affinity import derive_affinity
			from red_pill.session.store import SessionRegistry

			SessionRegistry().upsert_session(
				originator=f"dag:{self.job_id}",
				continuity_id=str(continuity),
				mission_id=mission or f"mission:job-{str(self.job_id)[:8]}",
				role="job",
				lineage_id=payload.get("lineage_id"),
				affinity=derive_affinity(workdir=str(self._workdir(payload)), mission_id=mission or None),
				title=str(payload.get("title") or f"dag {str(self.job_id)[:8]}"),
			)
			checkpoint["leg_originator"] = f"dag:{self.job_id}"
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo registrar leg dag:{self.job_id}: {exc}")
		return checkpoint

	def on_terminal(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any], status: str, reason: str = "") -> None:
		"""S2: el leg del job expira al terminar; no deja jobs muertos en el tablón."""
		if not getattr(self, "job_id", None):
			return
		try:
			from red_pill.session.store import SessionRegistry

			SessionRegistry().unregister_session(f"dag:{self.job_id}")
		except Exception as exc:
			logger.warning(f"[DagJob] no se pudo expirar leg dag:{self.job_id}: {exc}")

	def preflight(self, payload: Dict[str, Any]) -> None:
		from red_pill.jobs.drivers.base import JobDeferred

		workdir = self._workdir(payload)
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")
