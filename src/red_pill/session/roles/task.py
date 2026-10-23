"""Política del agente de tarea: digest compacto + puntero al tablón (pull)."""

from __future__ import annotations

from typing import Any, Dict

from red_pill.session.roles.base import RolePolicy, register


@register
class TaskPolicy(RolePolicy):
	name = "task"

	def references(self) -> Dict[str, Any]:
		return {"digest": "compact", "history": "minimal", "board": "pull"}
