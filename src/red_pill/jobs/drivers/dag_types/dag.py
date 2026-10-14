"""DAG node type `dag`: composition by RECIPE reference (RFC-JOB_DAG §4.5).

A stage of this type expands (at submit time) into a `compound` whose sub_etapas
are the referenced recipe's stages — so `step`/resume only ever see compounds and
leaves, never a recipe reference.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from red_pill.jobs.drivers.dag_manifest import _TYPE_COMPOUND, _TYPE_DAG, _apply_recipe_defaults

from .base import StageContext, StageType, register


class DagRefStageType(StageType):
	kind = _TYPE_DAG

	@property
	def is_recipe_ref(self) -> bool:
		return True

	def validate(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		recipe_ref = stage.get("recipe")
		if not isinstance(recipe_ref, str) or not recipe_ref:
			raise ValueError(f"dag_job stage '{stage_path}' type dag requires 'recipe' (nombre o ruta de receta).")
		if stage.get("minion") or stage.get("sub_etapas"):
			raise ValueError(f"dag_job dag stage '{stage_path}' must not carry minion/sub_etapas (vienen de la receta).")
		if recipe_ref in ctx.recipe_stack:
			raise ValueError(f"dag_job receta cíclica: '{recipe_ref}' ya está en la cadena {ctx.recipe_stack}.")
		sub_source, sub_payload, _prio, _parent, _is_seed = ctx.load_recipe(recipe_ref)
		if sub_source != "dag_job":
			raise ValueError(f"dag_job stage '{stage_path}' recipe '{recipe_ref}' es source '{sub_source}', no dag_job.")
		sub_stages = (sub_payload.get("manifest") or {}).get("stages")
		if not isinstance(sub_stages, list) or not sub_stages:
			raise ValueError(f"dag_job stage '{stage_path}' recipe '{recipe_ref}' no tiene manifest.stages.")
		ctx.validate_children(sub_stages, sub_payload, stage_path, ctx.recipe_stack + [recipe_ref])

	def compose(self, stage: Dict[str, Any], ctx: StageContext, recipe_stack: List[str]) -> Optional[Dict[str, Any]]:
		recipe_ref = stage["recipe"]
		if recipe_ref in recipe_stack:
			raise ValueError(f"dag_job receta cíclica: '{recipe_ref}' ya está en la cadena {recipe_stack}.")
		_sub_source, sub_payload, _prio, _parent, _is_seed = ctx.load_recipe(recipe_ref)
		sub_stages = copy.deepcopy((sub_payload.get("manifest") or {}).get("stages") or [])
		_apply_recipe_defaults(sub_stages, sub_payload)
		compound: Dict[str, Any] = {
			"id": stage["id"],
			"type": _TYPE_COMPOUND,
			"sub_etapas": ctx.expand_children(sub_stages, recipe_stack + [recipe_ref]),
		}
		for key in ("on_fail", "parallel", "depends_on"):
			if stage.get(key) is not None:
				compound[key] = stage[key]
		return compound


register(DagRefStageType())
