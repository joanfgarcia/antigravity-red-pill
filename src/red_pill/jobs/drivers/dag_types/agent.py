"""DAG node type `agent`: an executable leaf that delegates to an agent backend."""

from __future__ import annotations

from typing import Any, Dict

from red_pill.jobs.drivers.dag_manifest import _TYPE_AGENT

from .base import LeafStageType, StageContext, register


class AgentStageType(LeafStageType):
	kind = _TYPE_AGENT

	@property
	def report_suffix(self) -> str:
		# The agent writes its own role-schema report; the minion envelope must not
		# clobber that evidence (forge zero-trust contract) → separate suffix.
		return ".envelope.json"

	def _validate_kind(self, stage: Dict[str, Any], stage_path: str, minion_id: str, kind: str, ctx: StageContext) -> None:
		if kind != _TYPE_AGENT:
			raise ValueError(f"dag_job stage '{stage_path}' type mismatch: minion '{minion_id}' no es agéntico.")
		self._validate_agent_model(stage, stage_path, ctx)


register(AgentStageType())
