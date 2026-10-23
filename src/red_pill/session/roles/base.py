"""Base de las políticas de hidratación por rol (Fase 2, contrato `HydrationPolicy`).

El rol es DATO persistido (registro/env), nunca una inferencia del texto. Cada
rol declara solo su **referencia** al despertar; la visibilidad del tablón es
global (D16) y el detalle siempre es pull explícito.
"""

from __future__ import annotations

from typing import Any, Dict, Type, TypeVar

_POLICIES: Dict[str, "RolePolicy"] = {}

_P = TypeVar("_P", bound="RolePolicy")


class RolePolicy:
	"""Qué recibe un rol al despertar (digest/historia/tablón)."""

	name: str = "task"

	def references(self) -> Dict[str, Any]:
		"""Descriptor determinista: `digest` (global|compact|none), `history`, `board`."""
		return {"digest": "compact", "history": "minimal", "board": "pull"}


def register(policy_cls: Type[_P]) -> Type[_P]:
	"""Registra una política por su `name` (patrón registry del arnés, §10.8.3)."""
	instance = policy_cls()
	_POLICIES[instance.name] = instance
	return policy_cls


def policy_for(role: Any) -> RolePolicy:
	"""Política del rol; un rol desconocido degrada al mínimo (`task`)."""
	name = str(role or "task").strip().lower()
	return _POLICIES.get(name, _POLICIES["task"])
