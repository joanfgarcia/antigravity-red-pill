"""DAG payload/tree validation (RFC-JOB_DAG §7), dispatched via the dag_types registry.

The COMMON checks (id/charset/duplicate/type/on_fail/depends_on) live here; each
node type contributes its own checks through `StageType.validate`.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from red_pill.jobs.drivers.dag_manifest import _SAFE_STAGE_ID, _collect_ids
from red_pill.jobs.drivers.dag_types import StageContext, get_stage_type, registered_kinds
from red_pill.jobs.drivers.dag_types.base import RecipeLoader

_MISSION_RE = re.compile(r"^[a-z][a-z0-9_-]*:[^\s:]+$")
_ROLES = frozenset({"orchestrator", "job", "task", "spawn"})


def _validate_identity(payload: Dict[str, Any]) -> None:
	"""RFC-INTEROP-003 S0: campos opcionales de alma/misión, sin cambiarlos."""
	continuity = payload.get("continuity_id")
	if continuity is not None:
		try:
			uuid.UUID(str(continuity))
		except (ValueError, TypeError) as exc:
			raise ValueError(f"dag_job continuity_id inválido (UUID esperado): {continuity!r}") from exc
	parent_mission = payload.get("parent_mission_id")
	if parent_mission is not None and not _MISSION_RE.match(str(parent_mission)):
		raise ValueError(f"dag_job parent_mission_id inválido: {parent_mission!r}")
	role = payload.get("role")
	if role is not None and str(role) not in _ROLES:
		raise ValueError(f"dag_job role inválido: {role!r}")


def default_load_recipe(reference: str) -> Tuple[str, Dict[str, Any], int, Optional[str], bool]:
	"""Resolve a recipe with the SAME mechanism as the CLI (RECIPE_DIRS)."""
	from red_pill.jobs.recipes import load_recipe as _load

	return _load(reference, base_dir=None)


def _noop_children(stages: List[Dict[str, Any]], recipe_stack: List[str]) -> List[Dict[str, Any]]:
	return []


def validate_payload(payload: Dict[str, Any], load_recipe: RecipeLoader = default_load_recipe) -> None:
	"""Validate a dag_job payload EN EL SUBMIT (recursive over the manifest tree)."""
	if not payload.get("mission_id"):
		raise ValueError("dag_job payload requires 'mission_id'.")
	_validate_identity(payload)
	manifest = payload.get("manifest")
	if not isinstance(manifest, dict) or not manifest.get("workdir"):
		raise ValueError("dag_job manifest requires 'workdir'.")
	stages = manifest.get("stages")
	if not isinstance(stages, list) or not stages:
		raise ValueError("dag_job manifest requires 'stages' (non-empty).")
	seen: List[str] = []
	all_ids = _collect_ids(stages)
	validate_stages(stages, payload, seen, path="", all_ids=all_ids, load_recipe=load_recipe)


def validate_stages(
	stages: List[Dict[str, Any]],
	payload: Dict[str, Any],
	seen: List[str],
	path: str,
	recipe_stack: Optional[List[str]] = None,
	all_ids: Optional[Set[str]] = None,
	load_recipe: RecipeLoader = default_load_recipe,
) -> None:
	if recipe_stack is None:
		recipe_stack = []
	if all_ids is None:
		all_ids = set()
	# fan_out_from references a SIBLING source (same level, RFC §4.6). The LOCAL
	# scope matters when COMPOSING (`type: dag` embeds another recipe): the local
	# id 'discover' is not in the top-level `all_ids`.
	sibling_ids = {x.get("id") for x in stages}
	ctx = StageContext(
		payload=payload,
		sibling_ids=sibling_ids,
		all_ids=all_ids,
		seen=seen,
		recipe_stack=recipe_stack,
		load_recipe=load_recipe,
		validate_children=lambda sub, sub_payload, sub_path, stack: validate_stages(sub, sub_payload, seen, sub_path, stack, all_ids, load_recipe),
		expand_children=_noop_children,
	)
	valid = registered_kinds()
	for s in stages:
		sid = s.get("id")
		if not sid:
			raise ValueError("dag_job stage requires 'id'.")
		if not isinstance(sid, str) or not _SAFE_STAGE_ID.match(sid):
			raise ValueError(f"dag_job stage id '{sid}' inválido: usa [A-Za-z0-9_.-] empezando por letra/dígito (sin rutas).")
		stage_path = f"{path}/{sid}" if path else sid
		if stage_path in seen:
			raise ValueError(f"dag_job duplicate stage path '{stage_path}' (los ids son únicos globalmente).")
		seen.append(stage_path)

		stype = s.get("type")
		if stype not in valid:
			raise ValueError(f"dag_job stage '{stage_path}' type '{stype}' not in {'|'.join(valid)}.")
		# `on_fail` se documenta en el manifest (RFC §7) pero nunca se validaba:
		# una errata quedaba como 'warn' silencioso. Vale en cualquier nivel —
		# en compuestos lo heredan sus hojas (_resolve_on_fail).
		on_fail = s.get("on_fail")
		if on_fail is not None and on_fail not in ("warn", "stop"):
			raise ValueError(f"dag_job stage '{stage_path}' on_fail '{on_fail}' not in warn|stop.")

		handler = get_stage_type(stype)
		assert handler is not None  # stype ∈ valid
		handler.validate(s, stage_path, ctx)

		for dep in s.get("depends_on", []):
			# las deps referencian hermanos (ids del mismo nivel)
			dep_path = f"{path}/{dep}" if path else dep
			if dep_path not in seen:
				raise ValueError(f"dag_job stage '{stage_path}' depends_on unknown '{dep}'.")
