"""Entrega de eventos del tablón al arnés — adaptador de la Fase 5.

Qué resuelve
------------
El tablón (`mission_events`) publica; el coro lee por cursor (`fetch_events`,
digest del interceptor 12). Eso es **pull**: funciona siempre, pero solo cuando
el destinatario abre un turno. Este módulo añade el otro medio — el **nudge**:
coger un evento dirigido a un alma y convertirlo en un turno dentro de su arnés.

No es un segundo buzón. El evento **siempre** vive en `mission_events` (append
only, con triggers que impiden UPDATE/DELETE: `store.py:82-97`); aquí solo se
guarda **el estado de entrega** (`event_deliveries`), una fila por
(evento, alma). Borrar/reescribir el tablón para "marcar como leído" habría
roto el log.

Reglas que implementa (no inventa ninguna)
------------------------------------------
- **Dirección = `continuity_id` (D-05).** Un evento apunta a un ALMA, no a una
	sesión. El cuerpo (`provider:session_id`) se resuelve por presencia con
	`soul_notify.resolve_live_leg` — el mismo criterio que AD-090: un alma idle
	también se puede despertar; `ttl_state='expired'` no.
- **Un solo transporte.** La entrega pasa por el seam `_TRANSPORTS` de
	`core/soul_notify.py`. Este módulo NO invoca `opencode run` por su cuenta:
	si mañana `neon-link` ocupa el default, el nudge se repunta solo.
- **Fail-closed.** Si no hay cuerpo, si el arnés no tiene punto de inyección o
	si el transporte falla, el evento **se queda pendiente** en el tablón para el
	siguiente turno. Nada se pierde: el pull sigue estando ahí.
- **Pull-first.** El push solo vale hasta que el destinatario abre turno. Cuando
	el cursor del digest pasa el evento, `reconcile_pulled` lo cierra como
	`pulled`: empujarlo después sería duplicar lo que el digest ya anunció.
- **Sin bucles.** El estado de entrega es el cursor. `claim_delivery` es un CAS
	atómico (`BEGIN IMMEDIATE`, mismo patrón que D13 en `stage_claims`): dos
	entregadores no empujan el mismo evento. Un `in_flight` colgado más de
	`CLAIM_TTL_S` se puede reclamar (el entregador murió); pasado
	`MAX_PUSH_ATTEMPTS` el evento cierra como `given_up` y deja de reintentarse.

TABLA DE HONESTIDAD (por arnés)
-------------------------------
Medida en este repo, 2026-10-28. Sin maquillar: lo que no existe, no existe.

| arnés        | ¿punto de inyección? | cómo                                              | degradación                                        |
|--------------|----------------------|---------------------------------------------------|----------------------------------------------------|
| `opencode`   | SÍ                   | seam `cli` de `soul_notify`: `opencode run --session <id>` — inyecta turno o despierta el cuerpo idle. Antes se sondea `opencode session export <id>`: un id desconocido NO falla en `run`, crea una sesión con ese id | `stale_leg` (la sesión no existe: no se inyecta y el leg se caduca) o sonda fallida → pull |
| `claude_code`| SÍ (F6, 2026-10-30)  | seam `claude_socket` de `soul_notify`: una línea NDJSON por el socket de mensajería de la sesión (`CLAUDE_CODE_MESSAGING_SOCKET`, que el hook deja en el bridge por sesión). Entra en el turno en curso o despierta la sesión idle. NO sirve `claude --resume <id> -p`: es headless y abre el turno en otro proceso | pull si el bridge no tiene socket o la sesión ya no vive; el receptor puede retenerlo (`crossSessionInbound`) |
| `pi`         | NO (aquí)            | mismo caso: resume por cabecera de sesión (`swarm/bridges/pi.py`), headless | pull                                                |
| `telegram`   | NO (aquí)            | tiene bandeja (el chat del Operador) pero la salida vive **fuera** del repo (neon-link/gateway); lo de dentro es `notify_os`, que no es un turno | pull + señal de dolor del metabolismo                |

Dos limitaciones de los caminos que sí existen, dichas en la cara:

1. **Ningún seam confirma.** `_deliver_claude_socket` devuelve `True` cuando el
	socket acepta los bytes (el receptor aún puede retenerlo) y `_deliver_cli`
	cuando el hijo `opencode run` **arranca** (y `run --session <id desconocido>`
	no falla: abre otra sesión). Por eso el push cierra como **`handed_off`**
	(«en manos del transporte»). Lo promueve a **`delivered`** el ARNÉS receptor:
	su hook de inicio de turno ve `msg=<event_id>` en el prompt y la sesión es del
	alma destinataria (`acknowledge_seen`, AD-099). Hueco declarado: en Claude, un
	nudge que entra a mitad de turno llega como recordatorio, no dispara el hook y
	se queda en `handed_off`. El motivo lleva el rastro del CLI
	(`rastro=<fichero>`) para que el emisor pueda ver qué pasó aunque el llamante
	ya no exista.
2. **La política decide, este módulo ejecuta.** Cada evento dirigido pasa primero
	por el control de entrada del destinatario (`wake_policy.inbound_blocked`):
	`refuse` cierra el empuje (`skipped`, terminal — lo dijo el destinatario),
	`hold` o un estado ilegible lo difieren (sigue `pending`, lo recoge el pull).
	La matriz de roles (`WAKE_POLICY`, D-07) **aún no se aplica aquí**: es el gap
	declarado de C3 (ver `wake_policy.decide_wake`, ya probado, pendiente de
	cablear con registro de sesiones). Superficie pública: `red-pill session
	deliver` (`REDPILL_OPERATOR=1`).

Non-fatal por diseño: un fallo de BD o de transporte degrada a pull y se
registra; nunca tira el turno del llamante.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from red_pill.session import wake_policy
from red_pill.session.store import _INTERNAL_EVENT_TYPES, connect_session_db, sanitize_inline

logger = logging.getLogger(__name__)

# Estados del registro de entrega. `pending` puede ser implícito (sin fila = no
# entregado); las filas se crean al reclamar.
STATE_PENDING = "pending"
STATE_IN_FLIGHT = "in_flight"
STATE_DELIVERED = "delivered"
# El push salió por el transporte, sin acuse del arnés (ver la tabla). Terminal
# para el push: reempujarlo duplicaría el turno.
STATE_HANDED_OFF = "handed_off"
STATE_PULLED = "pulled"
STATE_GIVEN_UP = "given_up"
STATE_SKIPPED = "skipped"
# v8 (AD-095): el ack del destinatario. `delivered` es un hecho del transporte;
# `read` es lo que el alma dice haber visto. No hay `replied`: se sabe por el hilo.
STATE_READ = "read"
TERMINAL_STATES = frozenset({STATE_DELIVERED, STATE_HANDED_OFF, STATE_READ, STATE_PULLED, STATE_GIVEN_UP, STATE_SKIPPED})

# Ventana en la que un `in_flight` se considera en curso y no se reclama. Ha de
# cubrir el hilo daemon del transporte (`soul_notify.DELIVERY_TIMEOUT_S` = 120 s)
# más margen; por encima, se asume que el entregador murió a mitad.
CLAIM_TTL_S = 300.0
# Intentos de push antes de rendirse y dejar el evento en `given_up`. Corto: el
# push es un lujo, el pull es la entrega real.
MAX_PUSH_ATTEMPTS = 3

# Arnés → nombre del seam en `soul_notify._TRANSPORTS` (ver la tabla del
# docstring): añadir otro arnés aquí exige añadir antes su transporte al seam, no
# lo contrario.
INJECTION_POINTS: Dict[str, str] = {"opencode": "cli", "claude_code": "claude_socket"}

# Acuse por hook (RFC-INTEROP-001 §12 bis): cada nudge lleva `msg=<event_id>`. El
# hook de inicio de turno del arnés receptor lo ve en el prompt y promueve la fila
# a `delivered`: es el arnés, no el transporte, quien confirma. Solo cuenta si la
# sesión que recibe pertenece al alma destinataria (un `opencode run --session
# <id desconocido>` abre una sesión huérfana sin registro: no acusa nada).
#
# Los hooks NO importan el kernel: replican este patrón y esta sentencia tal cual
# (`seeds/settings/hooks/redpill_turn_start.py`, `seeds/opencode/plugins/
# redpill-scribe.js`). Un test de paridad lo vigila.
ACK_MARKER_RE = re.compile(r"\bmsg=([0-9a-f]{32})\b")
ACK_SQL = (
	"UPDATE event_deliveries SET state = 'delivered', reason = ?, updated_at = ?"
	" WHERE event_id = ? AND state IN ('in_flight', 'handed_off')"
	" AND continuity_id IN (SELECT continuity_id FROM session_registry"
	" WHERE originator = ? AND ttl_state != 'expired')"
)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS event_deliveries (
	event_id TEXT NOT NULL,
	continuity_id TEXT NOT NULL,
	state TEXT NOT NULL DEFAULT 'pending',
	attempts INTEGER NOT NULL DEFAULT 0,
	holder TEXT NOT NULL DEFAULT '',
	claimed_at REAL NOT NULL DEFAULT 0,
	reason TEXT NOT NULL DEFAULT '',
	updated_at REAL NOT NULL,
	PRIMARY KEY (event_id, continuity_id)
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_deliveries_soul_state ON event_deliveries(continuity_id, state)"


def _connect(db_path: Optional[str]):
	from red_pill.core.paths import get_session_db

	return connect_session_db(str(db_path) if db_path else str(get_session_db()))


def ensure_schema(db_path: Optional[str] = None) -> None:
	"""Crea la tabla de estado si no existe. Idempotente y non-fatal."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(_INDEX_DDL)
			conn.commit()
	except Exception as e:
		logger.warning(f"[delivery] no se pudo asegurar el esquema: {e}")


# ── Lectura de pendientes ────────────────────────────────────────────────────


def _soul_cursor_cond() -> str:
	"""Condición SQL del cursor del alma (pull-first).

	El cursor vive en `session_registry.last_seen_event_seq` por CUERPO; el alma lo
	toma por el MÁXIMO de sus cuerpos no expirados (un `switch_model` no lo
	reinicia). Un evento con `event_seq` por debajo ya lo anunció el digest: el
	push no es su canal. Se filtra AQUÍ, además de en `reconcile_pulled`, para que
	un reconcile perdido (handshake caído) no derive en un nudge duplicado.
	"""
	return (
		"e.event_seq > COALESCE((SELECT MAX(r.last_seen_event_seq) FROM session_registry r"
		" WHERE r.continuity_id = ? AND r.ttl_state != 'expired'), 0)"
	)


def pending_for_soul(continuity_id: str, *, limit: int = 20, db_path: Optional[str] = None) -> List[dict]:
	"""Eventos del tablón dirigidos a `continuity_id` y aún no entregados.

	Qué se excluye y por qué:
	- eventos internos de D23-SCORE (`decision_*`): son auditoría, no noticia.
	- `sealed`: son privados del cuerpo que los publicó; empujarlos los expondría.
	- notas `hidden`/`retracted`: la moderación ya las apartó del tablón.
	- eventos ya pasados por el cursor del digest (pull-first, ver `_soul_cursor_cond`).
	- eventos en estado terminal (`delivered`/`pulled`/`given_up`/`skipped`).

	Un `in_flight` **sí** aparece: puede estar colgado de un entregador muerto; es
	`claim_delivery` quien decide si se puede reclamar.
	"""
	soul = str(continuity_id or "").strip()
	if not soul:
		return []
	internal = tuple(sorted(_INTERNAL_EVENT_TYPES))
	placeholders = ",".join("?" * len(internal))
	sql = (
		"SELECT e.event_seq, e.event_id, e.type, e.mission_id, e.summary, e.ref,"
		" e.originator, e.continuity_id, e.created_at,"
		" e.verb, e.thread_id, e.hop, e.hop_max, e.expects_reply, e.value_class, e.expires_at,"
		" d.state AS delivery_state, d.attempts AS delivery_attempts"
		" FROM mission_events e"
		" LEFT JOIN event_deliveries d ON d.event_id = e.event_id AND d.continuity_id = ?"
		" LEFT JOIN note_status ns ON ns.event_id = e.event_id"
		" WHERE e.to_continuity = ? AND e.sealed = 0"
		f" AND e.type NOT IN ({placeholders})"
		" AND COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted')"
		" AND (e.expires_at IS NULL OR e.expires_at > ?)"
		f" AND {_soul_cursor_cond()}"
		" AND (d.event_id IS NULL OR d.state IN ('pending', 'in_flight'))"
		" ORDER BY e.event_seq ASC LIMIT ?"
	)
	params = [soul, soul, *internal, time.time(), soul, max(1, min(int(limit or 20), 200))]
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			rows = conn.execute(sql, tuple(params)).fetchall()
		return [dict(row) for row in rows]
	except Exception as e:
		logger.warning(f"[delivery] lectura de pendientes falló: {e}")
		return []


def get_delivery(event_id: str, continuity_id: str, *, db_path: Optional[str] = None) -> Optional[dict]:
	"""Estado de entrega de (evento, alma); None si no hay fila."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			row = conn.execute(
				"SELECT * FROM event_deliveries WHERE event_id = ? AND continuity_id = ?",
				(str(event_id or ""), str(continuity_id or "")),
			).fetchone()
		return dict(row) if row else None
	except Exception as e:
		logger.debug(f"[delivery] lectura falló: {e}")
		return None


# ── Estado de entrega (CAS) ─────────────────────────────────────────────────


def claim_delivery(
	*,
	event_id: str,
	continuity_id: str,
	holder: str,
	ttl_s: float = CLAIM_TTL_S,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> bool:
	"""Reserva el evento para este entregador. CAS atómico (D13).

	True si la reserva es nuestra; False si otro la tiene, si ya está cerrado o si
	la BD falla (**fail-closed**: nunca se asume la entrega). Un `in_flight` más
	viejo que `ttl_s` se puede reclamar: el entregador se cayó y el evento no debe
	quedarse en tierra de nadie.
	"""
	if not event_id or not continuity_id:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(_INDEX_DDL)
			conn.execute("BEGIN IMMEDIATE")
			try:
				conn.execute(
					"INSERT OR IGNORE INTO event_deliveries (event_id, continuity_id, state, attempts, holder, claimed_at, reason, updated_at)"
					" VALUES (?, ?, ?, 0, '', 0, '', ?)",
					(str(event_id), str(continuity_id), STATE_PENDING, stamp),
				)
				cur = conn.execute(
					"UPDATE event_deliveries SET state = ?, holder = ?, claimed_at = ?, updated_at = ?"
					" WHERE event_id = ? AND continuity_id = ?"
					" AND (state = 'pending' OR (state = 'in_flight' AND claimed_at < ?))",
					(STATE_IN_FLIGHT, str(holder or ""), stamp, stamp, str(event_id), str(continuity_id), stamp - float(ttl_s)),
				)
				if int(cur.rowcount or 0) != 1:
					conn.rollback()
					return False
				conn.commit()
				return True
			except Exception:
				conn.rollback()
				raise
	except Exception as e:
		logger.warning(f"[delivery] claim falló para {str(event_id)[:12]}: {e}")
		return False


def set_delivery_state(
	*,
	event_id: str,
	continuity_id: str,
	state: str,
	reason: str = "",
	attempts_delta: int = 0,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> bool:
	"""Cierra (o reabre) el estado de entrega. Non-fatal: False si no se pudo."""
	if not event_id or not continuity_id or state not in {
		STATE_PENDING,
		STATE_IN_FLIGHT,
		STATE_DELIVERED,
		STATE_HANDED_OFF,
		STATE_PULLED,
		STATE_GIVEN_UP,
		STATE_SKIPPED,
		STATE_READ,
	}:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(
				"INSERT INTO event_deliveries (event_id, continuity_id, state, attempts, holder, claimed_at, reason, updated_at)"
				" VALUES (?, ?, ?, ?, '', 0, ?, ?)"
				" ON CONFLICT(event_id, continuity_id) DO UPDATE SET"
				" state = excluded.state,"
				" attempts = event_deliveries.attempts + excluded.attempts,"
				" reason = excluded.reason,"
				" updated_at = excluded.updated_at"
				# Un acuse no retrocede: con el socket, el hook del receptor puede
				# confirmar ANTES de que el entregador escriba `handed_off`.
				" WHERE NOT (event_deliveries.state IN ('delivered', 'read')"
				" AND excluded.state IN ('pending', 'in_flight', 'handed_off'))",
				(str(event_id), str(continuity_id), state, max(0, int(attempts_delta)), str(reason or "")[:200], stamp),
			)
			conn.commit()
			return True
	except Exception as e:
		logger.warning(f"[delivery] no se pudo fijar estado {state} para {str(event_id)[:12]}: {e}")
		return False


def acknowledge_seen(originator: str, prompt: str, *, db_path: Optional[str] = None, now: Optional[float] = None) -> int:
	"""Acuse del arnés: el prompt que abre el turno de `originator` trae nudges.

	Referencia en Python de lo que hacen los hooks (misma regex, misma sentencia).
	Devuelve cuántas filas pasaron a `delivered`. Non-fatal: 0 ante cualquier fallo.
	"""
	ids = sorted(set(ACK_MARKER_RE.findall(str(prompt or ""))))
	origin = str(originator or "").strip()
	if not ids or not origin:
		return 0
	stamp = float(now) if now is not None else time.time()
	reason = f"ack_hook:{origin}"[:200]
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			total = 0
			for event_id in ids:
				total += int(conn.execute(ACK_SQL, (reason, stamp, event_id, origin)).rowcount or 0)
			conn.commit()
			return total
	except Exception as e:
		logger.warning(f"[delivery] acuse de {origin[:24]} no aplicado: {e}")
		return 0


def mark_read(event_id: str, continuity_id: str, *, db_path: Optional[str] = None, now: Optional[float] = None) -> bool:
	"""El alma declara leído un mensaje suyo (AD-095 §5). Detiene su vida útil.

	Idempotente: si no había fila (nunca se empujó) nace ya en `read`; el `inbox`
	lo mostraba como `queued`, así que el ack sin push es legítimo.
	"""
	return set_delivery_state(
		event_id=str(event_id or ""),
		continuity_id=str(continuity_id or ""),
		state=STATE_READ,
		reason="ack",
		db_path=db_path,
		now=now,
	)


def reconcile_pulled(continuity_id: str, *, until_seq: int, db_path: Optional[str] = None, now: Optional[float] = None) -> int:
	"""Cierra como `pulled` los pendientes que el cursor del digest ya anunció.

	El pull **gana**: si el destinatario abrió turno y el digest le contó el evento,
	empujarlo después es duplicarlo. Se registran también los eventos sin fila (el
	estado pending es implícito) para que el rastro quede, no solo el filtro.
	Devuelve cuántos cerró.
	"""
	soul = str(continuity_id or "").strip()
	ceiling = int(until_seq or 0)
	if not soul or ceiling <= 0:
		return 0
	stamp = float(now) if now is not None else time.time()
	count_sql = (
		"SELECT COUNT(*) AS n FROM event_deliveries WHERE continuity_id = ?"
		" AND state = 'pulled' AND reason = 'cursor_del_digest'"
	)
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			before = int((conn.execute(count_sql, (soul,)).fetchone() or {"n": 0})["n"])
			# 1) Los que aún no tienen fila: nacen ya cerrados como pulled.
			conn.execute(
				"INSERT OR IGNORE INTO event_deliveries (event_id, continuity_id, state, attempts, holder, claimed_at, reason, updated_at)"
				" SELECT e.event_id, ?, 'pulled', 0, '', 0, 'cursor_del_digest', ?"
				" FROM mission_events e WHERE e.to_continuity = ? AND e.event_seq <= ?",
				(soul, stamp, soul, ceiling),
			)
			# 2) Los que tenían fila abierta (pending/in_flight).
			conn.execute(
				"UPDATE event_deliveries SET state = ?, reason = 'cursor_del_digest', updated_at = ?"
				" WHERE continuity_id = ? AND state IN ('pending', 'in_flight')"
				" AND event_id IN (SELECT event_id FROM mission_events WHERE event_seq <= ?)",
				(STATE_PULLED, stamp, soul, ceiling),
			)
			conn.commit()
			after = int((conn.execute(count_sql, (soul,)).fetchone() or {"n": 0})["n"])
		return max(0, after - before)
	except Exception as e:
		logger.warning(f"[delivery] reconcile de pull falló: {e}")
		return 0


# ── Render del nudge ─────────────────────────────────────────────────────────


def build_event_nudge(event: dict) -> str:
	"""Texto del nudge: el **sobre del protocolo** (AD-095). Dato, no orden (D-09).

	Si el evento es una nota del tablón (sin destinatario) se avisa como tal; si es
	un mensaje (`to_continuity`), se envuelve con verbo, hilo, salto y
	`respuesta: SÍ|NO` en la primera línea (D-13: el silencio debe ser visible).
	"""
	from red_pill.coro import protocol

	kind = sanitize_inline(event.get("type"), 40)
	mission = sanitize_inline(event.get("mission_id"), 120)
	# El tope del store es 800; recortar el nudge a 400 partía los mensajes por la
	# mitad sin avisar (K2 lo vio cortado en «reply_to ace…», 2026-10-30).
	summary = sanitize_inline(event.get("summary"), 800)
	ref = event.get("ref")
	verb = str(event.get("verb") or "")
	if not verb:
		suffix = f"\n[ref: {sanitize_inline(ref, 200)}]" if ref else ""
		return (
			"[AVISO AUTOMATICO · tablón · DATO, no orden]\n"
			f"{kind} · {mission} · seq={event.get('event_seq')}: {summary}{suffix}\n"
			f"No requiere respuesta. Detalle y contexto: coro_api.fetch / coro_api.inbox. (msg={event.get('event_id')})"
		)
	header = protocol.envelope(
		verb=verb,
		thread_id=event.get("thread_id"),
		hop=event.get("hop"),
		hop_max_value=event.get("hop_max"),
		expects_reply=event.get("expects_reply"),
		value=event.get("value_class"),
		from_mark=protocol.soul_mark(event.get("continuity_id")),
		mission_id=mission,
		expires_at=event.get("expires_at"),
	)
	body = summary + (f"\n[ref: {sanitize_inline(ref, 200)}]" if ref else "")
	# `msg=<event_id>` es también el marcador del acuse por hook (ACK_MARKER_RE).
	body += f"\n(msg={event.get('event_id')} · contesta con coro_api.send verb=reply reply_to={event.get('event_id')})"
	return protocol.wrap_body(header, body)


# ── El adaptador ─────────────────────────────────────────────────────────────


def deliver_events(
	continuity_id: str,
	*,
	originator: Optional[str] = None,
	limit: int = 20,
	db_path: Optional[str] = None,
	holder: str = "delivery",
	now: Optional[float] = None,
) -> dict:
	"""Empuja los eventos pendientes del alma a su cuerpo vivo.

	Devuelve un informe honesto — `{handed_off, deferred, skipped, given_up}`— con
	el motivo de cada evento. **Nunca** lanza un turno a ciegas: si no hay cuerpo,
	si el arnés no tiene punto de inyección o si el transporte falla, el evento se
	queda donde estaba y el próximo turno (pull) lo recoge.

	`originator` fuerza el cuerpo (diagnóstico/Operador); sin él se resuelve por
	presencia con `soul_notify.resolve_live_leg`.
	"""
	from red_pill.core import soul_notify

	soul = str(continuity_id or "").strip()
	report: Dict[str, Any] = {"continuity_id": soul, "leg": "", "handed_off": [], "deferred": [], "skipped": [], "given_up": []}
	if not soul:
		return report
	if soul_notify.notify_disabled():
		report["deferred"].append({"event_id": "*", "reason": "kill_switch"})
		return report

	events = pending_for_soul(soul, limit=limit, db_path=db_path)
	if not events:
		return report

	leg = str(originator or "").strip() or str(soul_notify.resolve_live_leg(soul) or "")
	report["leg"] = leg
	if not leg or ":" not in leg:
		# Sin cuerpo vivo no se toca el estado: el evento sigue pendiente y el
		# siguiente turno lo ve por pull. Marcarlo aquí sería mentir dos veces
		# (ni se intentó) y cerrarlo sería perderlo para un futuro push.
		for ev in events:
			report["deferred"].append({"event_id": ev["event_id"], "reason": "no_live_body"})
		return report

	provider, _, session_id = leg.partition(":")
	if provider not in INJECTION_POINTS or not session_id:
		for ev in events:
			report["deferred"].append({"event_id": ev["event_id"], "reason": f"no_injection_point:{provider}"})
		return report

	for ev in events:
		event_id = str(ev.get("event_id") or "")
		if not event_id:
			continue
		if str(ev.get("originator") or "") == leg:
			# El cuerpo que publica es el que recibe: ya lo sabe. Empujárselo es
			# el eco que produce bucles de notificación.
			set_delivery_state(
				event_id=event_id,
				continuity_id=soul,
				state=STATE_SKIPPED,
				reason="self_authored",
				db_path=db_path,
				now=now,
			)
			report["skipped"].append({"event_id": event_id, "reason": "self_authored"})
			continue
		blocked = _wake_verdict(ev, soul, leg, db_path=db_path)
		if blocked is not None and blocked.terminal:
			# El destinatario dijo «no»: terminal. Reintentarlo sería desobedecerlo.
			set_delivery_state(
				event_id=event_id,
				continuity_id=soul,
				state=STATE_SKIPPED,
				reason=blocked.reason,
				db_path=db_path,
				now=now,
			)
			report["skipped"].append({"event_id": event_id, "reason": blocked.reason})
			continue
		if blocked is not None:
			# `hold`, matriz de roles que no casa, o sin fila en el registro: difiere.
			# El mensaje NO se pierde: sigue pendiente y el pull lo recoge al
			# reencarnar (AD-095: `park` es el camino barato y siempre funciona).
			report["deferred"].append({"event_id": event_id, "reason": blocked.reason})
			continue
		if not claim_delivery(event_id=event_id, continuity_id=soul, holder=holder, db_path=db_path, now=now):
			report["deferred"].append({"event_id": event_id, "reason": "claimed_by_other"})
			continue
		text = build_event_nudge(ev)
		try:
			ok = bool(soul_notify.notify_soul(soul, text, originator=leg))
		except Exception as e:  # el transporte no debe lanzar nunca al llamante
			logger.warning(f"[delivery] transporte lanzó excepción en {event_id[:12]}: {e}")
			ok = False
		if ok:
			trace = soul_notify.last_trace()
			set_delivery_state(
				event_id=event_id,
				continuity_id=soul,
				state=STATE_HANDED_OFF,
				reason=f"handed_to_transport:{INJECTION_POINTS[provider]}" + (f" rastro={trace}" if trace else ""),
				attempts_delta=1,
				db_path=db_path,
				now=now,
			)
			report["handed_off"].append({"event_id": event_id, "type": ev.get("type"), "seq": ev.get("event_seq"), "trace": trace})
			continue
		# El motivo real del transporte, no un genérico: "no salió" sin porqué fue lo
		# que dejó al Operador yendo a decírselo a mano (incidente 2026-10-30).
		why = f"transport_refused:{soul_notify.last_error() or 'desconocido'}"
		attempts = int(ev.get("delivery_attempts") or 0) + 1
		if attempts >= MAX_PUSH_ATTEMPTS:
			set_delivery_state(
				event_id=event_id,
				continuity_id=soul,
				state=STATE_GIVEN_UP,
				reason=f"push_attempts_exhausted:{why}",
				attempts_delta=1,
				db_path=db_path,
				now=now,
			)
			report["given_up"].append({"event_id": event_id, "reason": why})
		else:
			set_delivery_state(
				event_id=event_id,
				continuity_id=soul,
				state=STATE_PENDING,
				reason=why,
				attempts_delta=1,
				db_path=db_path,
				now=now,
			)
			report["deferred"].append({"event_id": event_id, "reason": why})
	return report


_SQL_ACTOR_BY_SOUL = "SELECT * FROM session_registry WHERE continuity_id = ? ORDER BY updated_at DESC LIMIT 1"
_SQL_ACTOR_BY_LEG = "SELECT * FROM session_registry WHERE originator = ? ORDER BY updated_at DESC LIMIT 1"


def _actor_for(conn, continuity_id: str, *, originator: str = "", by_leg: bool = False) -> "wake_policy.Actor":
	"""Actor desde `session_registry` (read-only). Sin fila = actor vacío.

	`by_leg=True` resuelve por el CUERPO (`originator`), no por el alma. Es lo que
	hace falta para el emisor: en un evento, `continuity_id` es el **destinatario**
	(D-05), así que buscar ahí al emisor devolvía su propia fila y la matriz
	casaba siempre consigo misma (`self`) — un agujero silencioso, no un permiso.
	"""
	row = None
	if by_leg:
		sql, value = _SQL_ACTOR_BY_LEG, str(originator or "").strip()
	else:
		sql, value = _SQL_ACTOR_BY_SOUL, str(continuity_id or "").strip()
	if value:
		try:
			row = conn.execute(sql, (value,)).fetchone()
		except Exception:
			row = None
	return wake_policy.Actor.from_row(dict(row) if row else None, originator=originator)


def _wake_verdict(ev: dict, soul: str, leg: str, *, db_path: Optional[str] = None):
	"""¿Puede este mensaje DESPERTAR a `soul`? (D-07 + controles de entrada).

	Devuelve `None` si puede, o el motivo del veto. Un mensaje de un alma que no
	está en el registro no casa con ninguna relación → pull (fail-closed).
	"""
	try:
		with _connect(db_path) as conn:
			recipient = _actor_for(conn, soul, originator=leg)
			sender = _actor_for(conn, "", originator=str(ev.get("originator") or ""), by_leg=True)
		decision = wake_policy.decide_wake(sender=sender, recipient=recipient, db_path=db_path)
	except Exception as e:
		# No saber no es permiso: se difiere.
		return wake_policy.Decision(False, f"wake_undecidable:{e}")
	return None if decision.allow else decision


def delivery_summary(continuity_id: str, *, db_path: Optional[str] = None) -> dict:
	"""Conteos por estado del alma (diagnóstico: cuánto se empujó y cuánto no)."""
	soul = str(continuity_id or "").strip()
	out: Dict[str, int] = {}
	if not soul:
		return out
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			rows = conn.execute("SELECT state, COUNT(*) AS n FROM event_deliveries WHERE continuity_id = ? GROUP BY state", (soul,)).fetchall()
		for row in rows:
			out[str(row["state"])] = int(row["n"])
	except Exception as e:
		logger.debug(f"[delivery] resumen falló: {e}")
	return out
