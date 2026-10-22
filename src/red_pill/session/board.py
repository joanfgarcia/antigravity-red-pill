"""Tabón de presencia como objeto (implementa `contracts.PresenceBoard`).

Adaptador fino sobre `core.session_index`: las funciones de módulo siguen siendo
la implementación de facto; esta clase da el punto de intercambio que pide el
plan 0b (una nueva implementación del tablón —anillo, etc.— sin tocar al resto).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class SessionBoard:
	"""Tabón de presencia: `build()` (datos) + `render()` (texto)."""

	def build(self, active_seconds: Optional[int] = None) -> List[Dict[str, Any]]:
		from red_pill.core.session_index import build_board

		return build_board(active_seconds)

	def render(
		self,
		board: List[Dict[str, Any]],
		active_min: Optional[int] = None,
		now: Optional[float] = None,
	) -> str:
		from red_pill.core.session_index import render_board

		return render_board(board, active_min, now)
