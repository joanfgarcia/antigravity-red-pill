"""DAG manifest composition (RFC-JOB_DAG §4.5), dispatched via the dag_types registry.

`expand_manifest` flattens `type: dag` stages into `compound` nodes with the
referenced recipe's stages, so `step`/resume only ever see compounds and leaves.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from red_pill.jobs.drivers.dag_types import StageContext, get_stage_type
from red_pill.jobs.drivers.dag_types.base import RecipeLoader

from .dag_validate import default_load_recipe


def _make_ctx(load_recipe: RecipeLoader) -> StageContext:
	ctx = StageContext(
		payload={},
		sibling_ids=set(),
		all_ids=set(),
		seen=[],
		recipe_stack=[],
		load_recipe=load_recipe,
		validate_children=lambda *_a, **_k: None,
		expand_children=lambda sub, stack: expand_stages(sub, stack, load_recipe, ctx),
	)
	return ctx


def expand_stages(stages: List[Dict[str, Any]], recipe_stack: List[str], load_recipe: RecipeLoader, ctx: StageContext) -> List[Dict[str, Any]]:
	out: List[Dict[str, Any]] = []
	for s in stages:
		handler = get_stage_type(s.get("type"))
		composed = handler.compose(s, ctx, recipe_stack) if handler else None
		out.append(composed if composed is not None else s)
	return out


def expand_manifest(payload: Dict[str, Any], load_recipe: RecipeLoader = default_load_recipe) -> Dict[str, Any]:
	"""Aplana las etapas `type: dag` a `compound` con las stages de la receta.

	Se llama en el SUBMIT (CLI/MCP) tras validate: el job se persiste con el árbol
	ya expandido, de modo que step()/checkpoint/resume trabajan SIEMPRE sobre
	compounds y hojas — el determinismo del resume no depende de que la receta siga
	igual en disco (RFC_JOB_DAG §4.5). Devuelve un payload nuevo (sin mutar el original).
	"""
	expanded = copy.deepcopy(payload)
	expanded["manifest"]["stages"] = expand_stages(expanded["manifest"]["stages"], [], load_recipe, _make_ctx(load_recipe))
	return expanded
