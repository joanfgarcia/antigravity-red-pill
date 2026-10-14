"""DAG node type `compound`: a structural node that groups `sub_etapas` (RFC §4.5)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from red_pill.jobs.drivers.dag_manifest import _TYPE_COMPOUND

from .base import StageContext, StageType, register


class CompoundStageType(StageType):
	kind = _TYPE_COMPOUND

	@property
	def is_compound(self) -> bool:
		return True

	def validate(self, stage: Dict[str, Any], stage_path: str, ctx: StageContext) -> None:
		if stage.get("minion"):
			raise ValueError(f"dag_job compound stage '{stage_path}' must not carry a minion.")
		sub = stage.get("sub_etapas")
		if not isinstance(sub, list) or not sub:
			raise ValueError(f"dag_job compound stage '{stage_path}' requires 'sub_etapas' (non-empty).")
		ctx.validate_children(sub, ctx.payload, stage_path, [])

	def compose(self, stage: Dict[str, Any], ctx: StageContext, recipe_stack: List[str]) -> Optional[Dict[str, Any]]:
		node = dict(stage)
		node["sub_etapas"] = ctx.expand_children(stage.get("sub_etapas", []), recipe_stack)
		return node


register(CompoundStageType())
