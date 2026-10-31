"""Política de despertar (wake) por rol + controles de entrada — Fase 5 (D-07).

Qué resuelve
------------
Empujar (nudge) abre un turno en la sesión de **otra** alma: cuesta cuota,
interrumpe y puede no ser deseado. D-07 fija el círculo — *el orquestador a su
cadena de mando y los pares de la misma misión; el resto, pull* — y aquí esa
regla vive **como dato** (`WAKE_POLICY` en `.env`), no cableada en el código,
para poder ampliarse sin migrar (el Operador avisa de que probablemente amplíe
el círculo, no lo estreche). Por el lado del receptor añaden los controles de
entrada por sesión: `accept` / `hold` / `refuse`.

Precedencia (manda lo de arriba; de arriba abajo)
-------------------------------------------------
1. **Kill switch del Operador** (`REDPILL_SOUL_NOTIFY_DISABLE`, `soul_notify`):
	si está ON, no se despierta a nadie cualesquiera que sean las reglas.
2. **Entrada del destinatario** (`session_inbound`): `refuse` cierra el empuje
	(`skipped`, terminal); `hold` lo difiere (el evento sigue pendiente). Gana a
	cualquier regla, incluida `any`.
3. **Matriz de roles** (`WAKE_POLICY`): reglas `from:relation` separadas por
	coma, evaluadas en orden; la primera que casa permite. Ninguna casa → pull.

Fail-closed (requisito 3 de la fase)
------------------------------------
`WAKE_POLICY` vacía, ausente, o la capa de config inaccesible → **no se despierta a
nadie por la matriz**: se aplica el default de fábrica (D-07) si la clave no está
configurada, y `rules_invalid` si la config no se puede leer o el texto está mal
formado, en lugar de caer a un default permisivo. Por el lado de la entrada, un
estado que no se puede leer (o que contiene un valor desconocido) se trata como
`hold`: diferir, no empujar. Lo contrario —despertar por no saber— es lo que esta
fase cierra.

D-09: la política no suspende constraints del Operador
-----------------------------------------------------
Este módulo solo responde a «¿despierto?». No toca el texto del mensaje, no le
da autoridad al emisor ni convierte un aviso en orden: el nudge sigue siendo
DATO (`delivery.build_event_nudge`, `soul_notify.build_job_notice`). Un `deny`
no borra nada del tablón (`mission_events` es append-only): el evento queda
pendiente y lo recoge el pull del siguiente turno.

Lo que NO hace
--------------
- No es un buzón: `session_inbound` es una fila por sesión (declaración), no un
	segundo inbox. El mensaje sigue viviendo en `mission_events` / MinionInbox.
- No decide el transporte: eso es el seam `_TRANSPORTS` de `core/soul_notify.py`
	(AD-090), único punto por donde sale un empuje.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from red_pill.session.store import connect_session_db, sanitize_inline

logger = logging.getLogger(__name__)

# Relaciones que pueden casar entre emisor y destinatario.
REL_SELF = "self"
REL_CHAIN = "chain"
REL_SAME_MISSION = "same_mission"
REL_SAME_CAMPAIGN = "same_campaign"
REL_ANY = "any"
RELATIONS = frozenset({REL_SELF, REL_CHAIN, REL_SAME_MISSION, REL_SAME_CAMPAIGN, REL_ANY})

# Default de fábrica (D-07, accepted_default): la propia alma, el orquestador a
# su cadena de mando y los pares de la misma misión. `same_campaign` y `any` son
# opt-in explícito del Operador.
DEFAULT_POLICY = f"*:{REL_SELF},orchestrator:{REL_CHAIN},*:{REL_SAME_MISSION}"
CONFIG_KEY = "WAKE_POLICY"

# Controles de entrada por sesión.
INBOUND_ACCEPT = "accept"
INBOUND_HOLD = "hold"
INBOUND_REFUSE = "refuse"
INBOUND_STATES = frozenset({INBOUND_ACCEPT, INBOUND_HOLD, INBOUND_REFUSE})

# Motivos (legibles en el reporte de entrega y en los logs).
REASON_NO_RULE = "no_rule"
REASON_NO_RECIPIENT = "no_recipient"
REASON_RULES_INVALID = "rules_invalid"
REASON_INBOUND_HOLD = "inbound_hold"
REASON_INBOUND_REFUSE = "inbound_refuse"
REASON_INBOUND_UNKNOWN = "inbound_unknown"

_ROLE_TOKEN = re.compile(r"^[a-z0-9_*-]+$")

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS session_inbound (
	continuity_id TEXT NOT NULL,
	originator TEXT NOT NULL DEFAULT '',
	state TEXT NOT NULL DEFAULT 'accept',
	reason TEXT NOT NULL DEFAULT '',
	updated_at REAL NOT NULL,
	PRIMARY KEY (continuity_id, originator)
)
"""


def _connect(db_path: Optional[str]):
	from red_pill.core.paths import get_session_db

	return connect_session_db(str(db_path) if db_path else str(get_session_db()))


def _clean(value: object) -> str:
	return str(value or "").strip()


@dataclass(frozen=True)
class Actor:
	"""Un participante del wake, visto como DATO (registro/tablón), nunca como texto."""

	continuity_id: str = ""
	originator: str = ""
	role: str = ""
	mission_id: str = ""
	campaign_id: str = ""
	lineage_id: str = ""

	@classmethod
	def from_row(cls, row: Optional[Dict], *, originator: str = "") -> "Actor":
		"""Actor desde una fila de `session_registry` (o vacía si no está registrada)."""
		data = row or {}
		return cls(
			continuity_id=_clean(data.get("continuity_id")),
			originator=_clean(originator or data.get("originator")),
			role=_clean(data.get("role")).lower(),
			mission_id=_clean(data.get("mission_id")),
			campaign_id=_clean(data.get("campaign_id")),
			lineage_id=_clean(data.get("lineage_id")),
		)


@dataclass(frozen=True)
class Decision:
	"""Veredicto de wake: `allow` + motivo legible (y la regla que casó, si hubo)."""

	allow: bool
	reason: str
	rule: str = ""

	@property
	def terminal(self) -> bool:
		"""True si el destino fue quien se negó: el push no debe reintentarse."""
		return self.reason == REASON_INBOUND_REFUSE

	@property
	def inbound(self) -> bool:
		"""True si el veredicto viene del control de entrada (no de la matriz)."""
		return self.reason.startswith("inbound_")


def parse_policy(raw: Optional[str]) -> Tuple[Tuple[Tuple[str, str], ...], str]:
	"""Reglas `from:relation` (CSV) → `((from, relation), ...)`, error vacío si es válida.

	Fail-closed: cualquier token raro (sin `:`, rol vacío, relación desconocida)
	invalora **toda** la política — no se queda parcialmente aplicada.
	"""
	text = _clean(raw)
	if not text:
		return (), f"{CONFIG_KEY} vacía"
	rules: List[Tuple[str, str]] = []
	for token in text.split(","):
		pair = token.strip()
		if not pair:
			return (), "token vacío"
		from_role, sep, relation = pair.partition(":")
		from_role = _clean(from_role).lower()
		relation = _clean(relation).lower()
		if not sep or not from_role or not relation:
			return (), f"regla sin 'from:relation': {pair!r}"
		if not _ROLE_TOKEN.match(from_role):
			return (), f"rol no admisible: {from_role!r}"
		if relation not in RELATIONS:
			return (), f"relación desconocida: {relation!r}"
		rules.append((from_role, relation))
	return tuple(rules), ""


def load_policy() -> Tuple[Tuple[Tuple[str, str], ...], str]:
	"""Lee `WAKE_POLICY` de la config. Config inaccesible → sin reglas (fail-closed).

	Clave **ausente o vacía** no es una política rota: es «no configurada» y cae
	al default de fábrica (D-07, `DEFAULT_POLICY`), que es el círculo aceptado. El
	fail-closed se reserva a lo que sí es un error del operador: texto presente y
	mal formado (relación desconocida, token sin `from:relation`).
	"""
	try:
		import red_pill.config as cfg

		raw = getattr(cfg.get_config(), CONFIG_KEY, None)
	except Exception as e:  # la capa de config no está: no se despierta a nadie
		logger.warning(f"[wake] config inaccesible ({e}); fail-closed: sin wake")
		return (), f"config: {e}"
	text = _clean(raw if isinstance(raw, str) else "")
	return parse_policy(text or DEFAULT_POLICY)


def relations_of(sender: Actor, recipient: Actor) -> frozenset:
	"""Relaciones que casan entre emisor y destinatario (todas las que se cumplen)."""
	out: set = set()
	if recipient.continuity_id or recipient.originator:
		out.add(REL_ANY)
	if sender.continuity_id and sender.continuity_id == recipient.continuity_id:
		out.add(REL_SELF)
	if sender.originator and sender.originator == recipient.originator:
		out.add(REL_SELF)
	same_mission = bool(sender.mission_id) and sender.mission_id == recipient.mission_id
	same_campaign = bool(sender.campaign_id) and sender.campaign_id == recipient.campaign_id
	same_lineage = bool(sender.lineage_id) and sender.lineage_id == recipient.lineage_id
	if same_mission:
		out.add(REL_SAME_MISSION)
	if same_campaign:
		out.add(REL_SAME_CAMPAIGN)
	# Cadena de mando: el orquestador mueve a quien cuelga de su misión/campaña/linaje.
	if sender.role == "orchestrator" and (same_mission or same_campaign or same_lineage):
		out.add(REL_CHAIN)
	return frozenset(out)


def can_wake(
	sender: Actor,
	recipient: Actor,
	*,
	rules: Optional[Tuple[Tuple[str, str], ...]] = None,
) -> Decision:
	"""¿Puede `sender` DESPERTAR (push) a `recipient` según la matriz de roles?

	Solo la matriz: los controles de entrada se comprueban antes en `decide_wake`.
	"""
	if not recipient.continuity_id and not recipient.originator:
		return Decision(False, REASON_NO_RECIPIENT)
	if rules is None:
		rules, error = load_policy()
		if error:
			return Decision(False, f"{REASON_RULES_INVALID}:{error}")
	held = relations_of(sender, recipient)
	if not held:
		return Decision(False, REASON_NO_RULE)
	for from_role, relation in rules:
		if relation in held and (from_role == "*" or from_role == sender.role):
			return Decision(True, relation, f"{from_role}:{relation}")
	return Decision(False, REASON_NO_RULE)


# ── Controles de entrada por sesión ─────────────────────────────────────────


def ensure_schema(db_path: Optional[str] = None) -> None:
	"""Crea la tabla de entrada si falta. Idempotente y non-fatal."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.commit()
	except Exception as e:
		logger.warning(f"[wake] no se pudo asegurar el esquema: {e}")


def set_inbound(
	continuity_id: str,
	state: str,
	*,
	originator: str = "",
	reason: str = "",
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> bool:
	"""Declara la postura de entrada de una sesión/alma. False si es inválida o falla la BD."""
	soul = _clean(continuity_id)
	desired = _clean(state).lower()
	if not soul or desired not in INBOUND_STATES:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(
				"INSERT INTO session_inbound (continuity_id, originator, state, reason, updated_at)"
				" VALUES (?, ?, ?, ?, ?)"
				" ON CONFLICT(continuity_id, originator) DO UPDATE SET"
				" state = excluded.state,"
				" reason = excluded.reason,"
				" updated_at = excluded.updated_at",
				(soul, _clean(originator), desired, sanitize_inline(reason, 200), stamp),
			)
			conn.commit()
			return True
	except Exception as e:
		logger.warning(f"[wake] no se pudo declarar la entrada {desired} para {soul[:8]}: {e}")
		return False


def get_inbound(
	continuity_id: str,
	*,
	originator: str = "",
	db_path: Optional[str] = None,
) -> str:
	"""Postura vigente: cuerpo exacto → alma entera → `accept`. Ilegible → `hold` (fail-closed)."""
	soul = _clean(continuity_id)
	leg = _clean(originator)
	if not soul:
		return INBOUND_HOLD
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			rows = conn.execute(
				"SELECT originator, state FROM session_inbound WHERE continuity_id = ?",
				(soul,),
			).fetchall()
	except Exception as e:
		logger.warning(f"[wake] estado de entrada ilegible para {soul[:8]} ({e}); fail-closed: hold")
		return INBOUND_HOLD
	by_leg = {_clean(r["originator"]): _clean(r["state"]).lower() for r in rows}
	found = by_leg.get(leg) if leg else None
	if found is None:
		found = by_leg.get("", INBOUND_ACCEPT)
	if found not in INBOUND_STATES:
		logger.warning(f"[wake] estado de entrada desconocido {found!r} para {soul[:8]}; fail-closed: hold")
		return INBOUND_HOLD
	return found


def list_inbound(*, continuity_id: str = "", db_path: Optional[str] = None) -> List[dict]:
	"""Declaraciones de entrada registradas (diagnóstico; nunca decide por sí solas)."""
	soul = _clean(continuity_id)
	sql = "SELECT continuity_id, originator, state, reason, updated_at FROM session_inbound"
	params: tuple = ()
	if soul:
		sql += " WHERE continuity_id = ?"
		params = (soul,)
	sql += " ORDER BY updated_at DESC"
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			rows = conn.execute(sql, params).fetchall()
		return [dict(row) for row in rows]
	except Exception as e:
		logger.debug(f"[wake] listado de entradas falló: {e}")
		return []


def decide_wake(
	*,
	sender: Actor,
	recipient: Actor,
	db_path: Optional[str] = None,
	rules: Optional[Tuple[Tuple[str, str], ...]] = None,
) -> Decision:
	"""Veredicto completo: control de entrada del destinatario y luego la matriz de roles.

	Las reglas se pueden cargar una vez por tanda y reutilizar (`rules=`) para no
	releer la config en cada evento; si no, se leen aquí (fail-closed si fallan).
	"""
	state = get_inbound(recipient.continuity_id, originator=recipient.originator, db_path=db_path)
	if state == INBOUND_REFUSE:
		return Decision(False, REASON_INBOUND_REFUSE)
	if state == INBOUND_HOLD:
		return Decision(False, REASON_INBOUND_HOLD)
	if state != INBOUND_ACCEPT:
		return Decision(False, REASON_INBOUND_UNKNOWN)
	return can_wake(sender, recipient, rules=rules)


def inbound_blocked(
	continuity_id: str,
	*,
	originator: str = "",
	db_path: Optional[str] = None,
) -> Optional[str]:
	"""Motivo de bloqueo por entrada del destinatario, o None si puede recibir wake.

	Atajo para quien solo tiene el destinatario (el aviso de fin de job de
	`soul_notify`: un job es hijo del alma que lo lanzó, cadena de mando propia).
	"""
	state = get_inbound(continuity_id, originator=originator, db_path=db_path)
	if state == INBOUND_ACCEPT:
		return None
	if state == INBOUND_REFUSE:
		return REASON_INBOUND_REFUSE
	if state == INBOUND_HOLD:
		return REASON_INBOUND_HOLD
	return REASON_INBOUND_UNKNOWN


def describe() -> dict:
	"""Retrato de la política vigente (para `red-pill session wake-policy`)."""
	rules, error = load_policy()
	return {
		"config_key": CONFIG_KEY,
		"default": DEFAULT_POLICY,
		"relations": sorted(RELATIONS),
		"inbound_states": sorted(INBOUND_STATES),
		"rules": [f"{frm}:{rel}" for frm, rel in rules],
		"error": error,
		"fail_closed": bool(error),
	}
