"""Política del leg de un job: digest compacto y tablón pull como `task`."""

from __future__ import annotations

from red_pill.session.roles.base import RolePolicy, register


@register
class JobPolicy(RolePolicy):
	name = "job"

	def references(self) -> dict:
		return {"digest": "compact", "history": "minimal", "board": "pull"}
