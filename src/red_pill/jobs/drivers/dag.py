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

	def preflight(self, payload: Dict[str, Any]) -> None:
		from red_pill.jobs.drivers.base import JobDeferred

		workdir = self._workdir(payload)
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")
