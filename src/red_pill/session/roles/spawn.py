"""Política del spawn: sin historia ni digest (bootstrap limpio por afinidad)."""

from __future__ import annotations

from typing import Any, Dict

from red_pill.session.roles.base import RolePolicy, register


@register
class SpawnPolicy(RolePolicy):
	name = "spawn"

	def references(self) -> Dict[str, Any]:
		return {"digest": "none", "history": "none", "board": "pull"}
