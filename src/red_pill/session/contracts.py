"""Contratos del subsistema de sesiones (Alma y Coro) — Protocols.

Primero los contratos, aunque hoy haya una sola implementación (plan 0b): cada
pieza es intercambiable sin tocar al resto.

- `SessionStore` → `store.SessionRegistry`.
- `PresenceBoard` → `board.SessionBoard`.
- `AffinityResolver` → `core.affinity.derive_affinity`.
- `HydrationPolicy` (Fase 2), `ClaimDriver` (Fase 4) y `Compactor` (Fase 3): declarados, sin implementación aún.

Estructurales: ninguna implementación necesita heredar de estos Protocols.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
	"""Registro de sesiones + reloj global (implementa `store.SessionRegistry`)."""

	def get_by_originator(self, originator: str) -> Optional[dict]: ...

	def get_by_continuity(self, continuity_id: str) -> List[dict]: ...

	def list_sessions(self, limit: int = 500) -> List[dict]: ...

	def upsert_session(self, **kwargs: Any) -> None: ...

	def next_global_turn(self, originator: str, affinity: Any = None) -> int: ...

	def get_max_global_turn(self) -> int: ...

	def add_event(self, **kwargs: Any) -> dict: ...

	def fetch_events(self, mission_id: str, **kwargs: Any) -> List[dict]: ...

	def count_events(self, mission_id: str, **kwargs: Any) -> int: ...


@runtime_checkable
class PresenceBoard(Protocol):
	"""Tabón de presencia (implementa `board.SessionBoard`)."""

	def build(self, active_seconds: Optional[int] = None) -> List[Dict[str, Any]]: ...

	def render(
		self,
		board: List[Dict[str, Any]],
		active_min: Optional[int] = None,
		now: Optional[float] = None,
	) -> str: ...


@runtime_checkable
class MirrorStore(Protocol):
	"""Espejo canónico de turnos por alma (implementa `mirror.SessionMirror`).

	`tool_calls` viaja como lista OpenAI íntegra (no como marcador de texto): es
	lo que permite replay cruzado con herramientas. `append_*` es idempotente por
	`(continuity_id, originator, source_ref)` cuando el turno trae `source_ref`.
	"""

	def append_turn(self, **kwargs: Any) -> Optional[dict]: ...

	def append_turns(self, continuity_id: str, turns: List[dict], **kwargs: Any) -> int: ...

	def read_turns(self, continuity_id: str, *, since_seq: int = 0, limit: Optional[int] = None, statuses: Optional[List[str]] = None) -> List[dict]: ...

	def count_turns(self, continuity_id: str) -> int: ...

	def last_seq(self, continuity_id: str) -> int: ...


class AffinityResolver(Protocol):
	"""Resolver determinista de afinidad (`core.affinity.derive_affinity`)."""

	def __call__(
		self,
		*,
		workdir: Optional[str] = None,
		mission_id: Optional[str] = None,
		explicit: Any = None,
		campaign_id: Optional[str] = None,
	) -> List[str]: ...


class ModelDriver(Protocol):
	"""Bridge ejecutable mínimo que `switch_model` necesita (sin acoplarse a uno).

	`ConversationResult`-like: el resultado debe exponer `response`, `conversation_id`
	y `error` (atributos o claves). Misma familia → `continue_conversation`;
	cruzado → `prompt` con el historial renderizado.
	"""

	def prompt(self, text: str, **kwargs: Any) -> Any: ...

	def continue_conversation(self, text: str, **kwargs: Any) -> Any: ...


class HydrationPolicy(Protocol):
	"""Qué referencia recibe cada rol al despertar (Fase 2; `session.roles`)."""

	def references(self) -> Dict[str, Any]: ...


class ClaimDriver(Protocol):
	"""Reclamo de etapa entre almas (Fase 4; montado-desactivado)."""

	def try_claim(self, claim_key: str, *, owner: str, ttl_s: float) -> bool: ...

	def renew(self, claim_key: str, *, owner: str, ttl_s: float) -> bool: ...

	def release(self, claim_key: str, *, owner: str) -> None: ...


class Compactor(Protocol):
	"""Compactación como servicio (Fase 3)."""

	def maybe_compact(self, continuity_id: str, messages: List[dict], *, threshold: int) -> List[dict]: ...
