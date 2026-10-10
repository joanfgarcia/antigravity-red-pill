"""Subsistema de sesiones (Alma y Coro).

`identity` (puro: emisión de alma + resolución de misión + tag `<session>`) y
`store` (`session.db`: reloj global + registro de sesiones). El diseño ratificado
vive en el DECISION_LOG del repo.
"""

from red_pill.session.identity import (
	decorate_with_session_tag,
	new_continuity_id,
	resolve_default_mission,
)
from red_pill.session.store import SessionRegistry

__all__ = [
	"SessionRegistry",
	"decorate_with_session_tag",
	"new_continuity_id",
	"resolve_default_mission",
]
