"""DAG node type `command`: an executable leaf that runs a CLI command via a minion."""

from __future__ import annotations

from typing import Any, Dict

from red_pill.jobs.drivers.dag_manifest import _TYPE_AGENT, _TYPE_COMMAND

from .base import LeafStageType, StageContext, register


class CommandStageType(LeafStageType):
	kind = _TYPE_COMMAND

	def _validate_kind(self, stage: Dict[str, Any], stage_path: str, minion_id: str, kind: str, ctx: StageContext) -> None:
		if kind == _TYPE_AGENT:
			raise ValueError(f"dag_job stage '{stage_path}' type mismatch: minion '{minion_id}' es agéntico, no '{self.kind}'.")


register(CommandStageType())
