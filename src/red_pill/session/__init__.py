"""Subsistema de sesiones (Alma y Coro).

`identity` (puro: emisión de alma + resolución de misión + tag `<session>`) y
`store` (`session.db`: reloj global + registro de sesiones). Ver
RFC_ALMA_Y_CORO / RFC_CONSCIENCIA_MULTISESION (desk) para el diseño.
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
