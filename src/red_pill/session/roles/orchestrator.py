"""Política del orquestador: sala de guerra global + historia acotada por afinidad."""

from __future__ import annotations

from typing import Any, Dict

from red_pill.session.roles.base import RolePolicy, register


@register
class OrchestratorPolicy(RolePolicy):
	name = "orchestrator"

	def references(self) -> Dict[str, Any]:
		return {"digest": "global", "history": "affinity", "board": "global"}
