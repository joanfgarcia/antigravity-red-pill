"""Subsistema de sesiones (Alma y Coro).

`identity` (puro: emisión de alma + resolución de misión + tag `<session>`),
`store` (`session.db`: reloj global + registro de sesiones), `board` (tablón de
presencia) y `contracts` (Protocols). El diseño ratificado vive en el
DECISION_LOG del repo.
"""

from red_pill.session.board import SessionBoard
from red_pill.session.compactor import Compactor
from red_pill.session.identity import (
	decorate_with_session_tag,
	new_continuity_id,
	resolve_default_mission,
)
from red_pill.session.lease import LeaseStore
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry

__all__ = [
	"Compactor",
	"LeaseStore",
	"SessionBoard",
	"SessionMirror",
	"SessionRegistry",
	"decorate_with_session_tag",
	"new_continuity_id",
	"resolve_default_mission",
]
