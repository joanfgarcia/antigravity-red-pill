"""Base of the DAG stage-type registry (RFC-JOB_DAG, CONVENTIONS §10.8.3).

A stage type lives in its own module and self-registers (see `__init__`). The
validator/composer/executor dispatch by the registry KEY (`stage["type"]`) — never
by an `if type ==` ladder — so adding a new DAG node is: write its module +
register it. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from red_pill.jobs.drivers.dag_manifest import _TYPE_AGENT, _resolve_minion_kind

RecipeLoader = Callable[[str], Tuple[str, Dict[str, Any], int, Optional[str], bool]]
ValidateChildren = Callable[[List[Dict[str, Any]], Dict[str, Any], str, List[str]], None]
ExpandChildren = Callable[[List[Dict[str, Any]], List[str]], List[Dict[str, Any]]]


@dataclass
class StageContext:
	"""Shared services a stage type needs while validating/composing.

	Callables are injected at construction (no import back into the validator /
	composer → no cycle). `seen` is the shared accumulator of stage paths (mutable).
	"""

	payload: Dict[str, Any]
	sibling_ids: Set[Any]
	all_ids: Set[str]
	seen: List[str]
	recipe_stack: List[str]
	load_recipe: RecipeLoader
	validate_children: ValidateChildren
	expand_children: ExpandChildren


class StageType:
	"""One kind of DAG node. Subclasses override `kind` and the hooks they need."""

	kind: str = ""

	@property
	def is_compound(self) -> bool:
		"""True if the node carries `sub_etapas` (recurse on validate/compose)."""
		return False

	@property
	def is_recipe_ref(self) -> bool:
		"""True if the node expands by RECIPE reference (`type: dag`)."""
		return False

	@property
	def report_suffix(self) -> str:
		"""Report filename suffix for this stage kind (`.json` vs `.envelope.json`)."""
		return ".json"

	def validate(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		"""Type-specific validation (COMMON checks are done by the validator)."""
		raise NotImplementedError

	def compose(self, stage: Dict[str, Any], ctx: StageContext, recipe_stack: List[str]) -> Optional[Dict[str, Any]]:
		"""Return the composed node, or None to leave the stage untouched (leaf)."""
		return None


class LeafStageType(StageType):
	"""Shared validation for executable leaves (`agent`, `command`)."""

	def validate(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		minion_id = stage.get("minion")
		if not minion_id:
			raise ValueError(f"dag_job stage '{stage_path}' requires 'minion'.")
		kind = _resolve_minion_kind(minion_id)
		if kind is None:
			raise ValueError(f"dag_job stage '{stage_path}' minion '{minion_id}' no registrado en MinionFactory.")
		self._validate_kind(stage, stage_path, str(minion_id), kind, ctx)
		self._validate_fanout(stage, stage_path, ctx)

	def _validate_kind(self, stage: Dict[str, Any], stage_path: str, minion_id: str, kind: str, ctx: StageContext) -> None:
		raise NotImplementedError

	def _validate_fanout(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		"""Fan-out por items (RFC §4.6): referencia existente, distinta de sí misma, solo en hojas."""
		sid = stage.get("id")
		fof = stage.get("fan_out_from")
		if fof is None:
			return
		if not isinstance(fof, str) or not fof:
			raise ValueError(f"dag_job stage '{stage_path}' fan_out_from must be a stage id.")
		if fof == sid:
			raise ValueError(f"dag_job stage '{stage_path}' fan_out_from no puede referenciarse a sí misma.")
		if fof not in ctx.sibling_ids and fof not in ctx.all_ids:
			raise ValueError(f"dag_job stage '{stage_path}' fan_out_from unknown '{fof}' (no existe ningún id de etapa así).")

	def _validate_agent_model(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		"""Fail-safe de modelos (fleco 3 del RFC): TODA etapa agéntica exige model real."""
		model = stage.get("model") or ctx.payload.get("model")
		if not model or model == "flash":
			raise ValueError(
				f"dag_job stage '{stage_path}' (agent) sin modelo configurado. "
				"'flash' es el placeholder del default, no una config activa. "
				"Indica 'model' con un modelo real (p.ej. opencode-go/deepseek-v4-pro). "
				"Bloqueado por seguridad (fail-safe de modelos)."
			)
		if not stage.get("prompt"):
			raise ValueError(f"dag_job agent stage '{stage_path}' requires 'prompt'.")


__all__ = ["StageContext", "StageType", "LeafStageType", "register", "get_stage_type", "registered_kinds", "_TYPE_AGENT"]


# ── Registry (CONVENTIONS §10.8.3): each type module registers itself on import ──
_STAGE_TYPES: Dict[str, StageType] = {}


def register(stage_type: StageType) -> StageType:
	"""Register a DAG node type by its `kind` key (self-registration)."""
	if not stage_type.kind:
		raise ValueError("StageType.kind no puede estar vacío.")
	_STAGE_TYPES[stage_type.kind] = stage_type
	return stage_type


def get_stage_type(kind: Optional[str]) -> Optional[StageType]:
	"""The registered node type for a `stage['type']`, or None if unknown."""
	return _STAGE_TYPES.get(kind or "")


def registered_kinds() -> Tuple[str, ...]:
	"""All registered node-type keys (order = registration order)."""
	return tuple(_STAGE_TYPES)
