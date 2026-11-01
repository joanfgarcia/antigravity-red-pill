"""Entrega de eventos del tablón al arnés — recibos, no estado de transporte.

Qué guarda y qué NO
-------------------
- `mission_events` sigue siendo la única verdad del contenido (append-only).
- **`message_receipts`** guarda solo lo que el alma o el pull saben:
	`handed_off` (el transporte lo tomó), `read` (el cuerpo lo acusó con `msg=`),
	`pulled` (el cursor del digest lo pasó) y `skipped` (eco propio o rechazo).
- **El estado de transporte vive en neon-link**: `outbox` (PENDING/SENT/FAILED),
	`retries`, backoff y `dead_letters`. Este módulo no lleva `in_flight`,
	`attempts`, `holder` ni `given_up`: eso era `event_deliveries`, **retirada** en
	S2.2. La tabla vieja se migra una vez a `message_receipts` y se elimina.

Reglas que implementa
---------------------
- **Dirección = `continuity_id` (D-05).** El cuerpo se resuelve por presencia con
	`soul_notify.resolve_live_leg` (idle también vale; `ttl_state='expired'` no).
- **Un solo transporte.** El push pasa por el seam `_TRANSPORTS` de
	`core/soul_notify.py`; no abre otro canal.
- **Fail-closed / pull-first.** Sin cuerpo, sin punto de inyección o transporte
	caído, el evento se queda pendiente y el siguiente turno lo recoge. El pull
	cierra como `pulled`; reempujarlo sería duplicar lo que el digest ya anunció.
- **Sin CAS de entrega.** El broker de neon-link es el único que llama a este
	módulo por evento y ya tiene la fila del outbox como claim. Un `handed_off`
	escrito por el push evita reempujes manuales; el `read` gana siempre.
- **Aviso de job**: un `originator=job:*` auto-dirigido puede despertar a su alma
	(cadena de mando AD-090); los controles `refuse`/`hold` se respetan antes.

TABLA DE HONESTIDAD (por arnés)
-------------------------------
| arnés | punto de inyección | cómo | degradación |
|---|---|---|---|
| `opencode` | SÍ | `opencode run --session <id>` (sonda previa `session export`) | `stale_leg`/pull |
| `claude_code` | SÍ | socket NDJSON de la sesión | pull si no hay socket |
| `pi` | NO (aquí) | resume headless | pull |
| `telegram` | NO (aquí) | bandeja fuera del repo | pull + señal |

Ningún seam confirma: el push cierra como `handed_off`; lo promueve a `read` el
hook del arnés que ve `msg=<event_id>` en el prompt. Non-fatal por diseño.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from red_pill.session import wake_policy
from red_pill.session.store import _INTERNAL_EVENT_TYPES, connect_session_db, sanitize_inline

logger = logging.getLogger(__name__)

# Recibos del alma/pull. El transporte NO vive aquí.
STATE_HANDED_OFF = "handed_off"
STATE_READ = "read"
STATE_PULLED = "pulled"
STATE_SKIPPED = "skipped"
VALID_RECEIPTS = frozenset({STATE_HANDED_OFF, STATE_READ, STATE_PULLED, STATE_SKIPPED})
TERMINAL_STATES = frozenset({STATE_READ, STATE_PULLED, STATE_SKIPPED, STATE_HANDED_OFF})

# Arnés → seam de `soul_notify._TRANSPORTS`.
INJECTION_POINTS: Dict[str, str] = {"opencode": "cli", "claude_code": "claude_socket"}

# Acuse por hook: el hook del arnés ve `msg=<event_id>` y escribe `read` para el
# alma del cuerpo que abrió el turno. Los hooks copian esta sentencia literal.
ACK_MARKER_RE = re.compile(r"\bmsg=([0-9a-f]{32})\b")
ACK_SQL = (
	"INSERT INTO message_receipts (event_id, continuity_id, state, reason, updated_at) SELECT ?, r.continuity_id, 'read', ?, ? FROM session_registry r WHERE r.originator = ? AND r.ttl_state != 'expired' AND EXISTS (SELECT 1 FROM mission_events e WHERE e.event_id = ? AND e.to_continuity = r.continuity_id) ON CONFLICT(event_id, continuity_id) DO UPDATE SET state = 'read', reason = excluded.reason, updated_at = excluded.updated_at WHERE message_receipts.state NOT IN ('read', 'pulled')"
)

_RECEIPT_DDL = """
CREATE TABLE IF NOT EXISTS message_receipts (
	event_id TEXT NOT NULL,
	continuity_id TEXT NOT NULL,
	state TEXT NOT NULL,
	reason TEXT NOT NULL DEFAULT '',
	updated_at REAL NOT NULL,
	PRIMARY KEY (event_id, continuity_id)
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_receipts_soul_state ON message_receipts(continuity_id, state)"


def _connect(db_path: Optional[str]):
	from red_pill.core.paths import get_session_db

	return connect_session_db(str(db_path) if db_path else str(get_session_db()))


def ensure_schema(db_path: Optional[str] = None) -> None:
	"""Crea `message_receipts` y retira `event_deliveries` una sola vez."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			conn.execute(_INDEX_DDL)
			_migrate_legacy_receipts(conn)
			conn.commit()
	except Exception as e:
		logger.warning(f"[delivery] no se pudo asegurar el esquema: {e}")


def _migrate_legacy_receipts(conn) -> None:
	"""Copia los recibos útiles de `event_deliveries` y elimina la tabla vieja.

	`delivered` era el acuse del cuerpo (`read`); `handed_off`/`pulled`/`skipped`
	se conservan. `pending`/`in_flight`/`given_up` no eran recibos: se descartan
	(la entrega la gobierna el outbox de neon-link). La tabla se elimina para que
	no vuelva a haber dos fuentes de verdad.
	"""
	exists = conn.execute(
		"SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_deliveries'"
	).fetchone()
	if not exists:
		return
	conn.execute(
		"INSERT OR IGNORE INTO message_receipts (event_id, continuity_id, state, reason, updated_at)"
		" SELECT event_id, continuity_id,"
		" CASE state"
		"   WHEN 'delivered' THEN 'read'"
		"   WHEN 'read' THEN 'read'"
		"   WHEN 'handed_off' THEN 'handed_off'"
		"   WHEN 'pulled' THEN 'pulled'"
		"   WHEN 'skipped' THEN 'skipped'"
		" END,"
		" reason, updated_at"
		" FROM event_deliveries"
		" WHERE state IN ('delivered','read','handed_off','pulled','skipped')"
	)
	conn.execute("DROP TABLE event_deliveries")
	logger.info("[delivery] event_deliveries migrada a message_receipts y retirada")


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


def pending_for_soul(
	continuity_id: str,
	*,
	limit: int = 20,
	db_path: Optional[str] = None,
	event_id: Optional[str] = None,
) -> List[dict]:
	"""Eventos del tablón dirigidos a `continuity_id` sin recibo todavía.

	Excluye: eventos internos de D23-SCORE, `sealed`, notas ocultas/retiradas,
	los ya pasados por el cursor del digest (pull-first) y cualquier evento que
	ya tenga un recibo (`handed_off`/`read`/`pulled`/`skipped`). El estado de
	transporte no se consulta aquí: vive en el outbox de neon-link.
	"""
	soul = str(continuity_id or "").strip()
	if not soul:
		return []
	internal = tuple(sorted(_INTERNAL_EVENT_TYPES))
	placeholders = ",".join("?" * len(internal))
	event_filter = ""
	extra: List[Any] = []
	if str(event_id or "").strip():
		event_filter = " AND e.event_id = ?"
		extra = [str(event_id).strip()]
	sql = (
		"SELECT e.event_seq, e.event_id, e.type, e.mission_id, e.summary, e.ref,"
		" e.originator, e.continuity_id, e.created_at,"
		" e.verb, e.thread_id, e.hop, e.hop_max, e.expects_reply, e.value_class, e.expires_at,"
		" r.state AS delivery_state"
		" FROM mission_events e"
		" LEFT JOIN message_receipts r ON r.event_id = e.event_id AND r.continuity_id = ?"
		" LEFT JOIN note_status ns ON ns.event_id = e.event_id"
		" WHERE e.to_continuity = ? AND e.sealed = 0"
		f" AND e.type NOT IN ({placeholders})"
		" AND COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted')"
		" AND (e.expires_at IS NULL OR e.expires_at > ?)"
		f" AND {_soul_cursor_cond()}"
		" AND r.event_id IS NULL"
		f"{event_filter}"
		" ORDER BY e.event_seq ASC LIMIT ?"
	)
	params = [soul, soul, *internal, time.time(), soul, *extra, max(1, min(int(limit or 20), 200))]
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			rows = conn.execute(sql, tuple(params)).fetchall()
		return [dict(row) for row in rows]
	except Exception as e:
		logger.warning(f"[delivery] lectura de pendientes falló: {e}")
		return []


def get_receipt(event_id: str, continuity_id: str, *, db_path: Optional[str] = None) -> Optional[dict]:
	"""Recibo de (evento, alma); None si no hay fila."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			row = conn.execute(
				"SELECT * FROM message_receipts WHERE event_id = ? AND continuity_id = ?",
				(str(event_id or ""), str(continuity_id or "")),
			).fetchone()
		return dict(row) if row else None
	except Exception as e:
		logger.debug(f"[delivery] lectura de recibo falló: {e}")
		return None


def set_receipt(
	*,
	event_id: str,
	continuity_id: str,
	state: str,
	reason: str = "",
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> bool:
	"""Escribe un recibo (`handed_off`/`read`/`pulled`/`skipped`). Non-fatal.

	`read` no retrocede: un `handed_off`/`pulled` posterior no puede borrar el
	acuse del cuerpo. El estado de transporte no se toca aquí.
	"""
	if not event_id or not continuity_id or state not in VALID_RECEIPTS:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			conn.execute(
				"INSERT INTO message_receipts (event_id, continuity_id, state, reason, updated_at)"
				" VALUES (?, ?, ?, ?, ?)"
				" ON CONFLICT(event_id, continuity_id) DO UPDATE SET"
				" state = excluded.state, reason = excluded.reason, updated_at = excluded.updated_at"
				" WHERE NOT (message_receipts.state = 'read' AND excluded.state != 'read')",
				(str(event_id), str(continuity_id), state, str(reason or "")[:200], stamp),
			)
			conn.commit()
			return True
	except Exception as e:
		logger.warning(f"[delivery] no se pudo escribir recibo {state} para {str(event_id)[:12]}: {e}")
		return False


def acknowledge_seen(originator: str, prompt: str, *, db_path: Optional[str] = None, now: Optional[float] = None) -> int:
	"""Acuse del hook: el prompt de `originator` trae `msg=<event_id>`.

	Escribe `read` para el alma del cuerpo que abrió el turno. Devuelve cuántas
	filas se escribieron. Non-fatal: 0 ante cualquier fallo.
	"""
	ids = sorted(set(ACK_MARKER_RE.findall(str(prompt or ""))))
	origin = str(originator or "").strip()
	if not ids or not origin:
		return 0
	stamp = float(now) if now is not None else time.time()
	reason = f"ack_hook:{origin}"[:200]
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			total = 0
			for event_id in ids:
				total += int(conn.execute(ACK_SQL, (event_id, reason, stamp, origin, event_id)).rowcount or 0)
			conn.commit()
			return total
	except Exception as e:
		logger.warning(f"[delivery] acuse de {origin[:24]} no aplicado: {e}")
		return 0


def mark_read(event_id: str, continuity_id: str, *, db_path: Optional[str] = None, now: Optional[float] = None) -> bool:
	"""El alma declara leído un mensaje suyo. Idempotente."""
	return set_receipt(
		event_id=str(event_id or ""),
		continuity_id=str(continuity_id or ""),
		state=STATE_READ,
		reason="ack",
		db_path=db_path,
		now=now,
	)


def reconcile_pulled(continuity_id: str, *, until_seq: int, db_path: Optional[str] = None, now: Optional[float] = None) -> int:
	"""Cierra como `pulled` los eventos que el cursor del digest ya anunció.

	El pull gana: reempujar lo que el digest contó sería duplicarlo. Crea recibos
	para los que no tenían y promueve a `pulled` los `handed_off`; un `read` no se
	toca. Devuelve cuántos cerró.
	"""
	soul = str(continuity_id or "").strip()
	ceiling = int(until_seq or 0)
	if not soul or ceiling <= 0:
		return 0
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_RECEIPT_DDL)
			before = int(
				(conn.execute(
					"SELECT COUNT(*) AS n FROM message_receipts WHERE continuity_id = ?"
					" AND state = 'pulled' AND reason = 'cursor_del_digest'",
					(soul,),
				).fetchone() or {"n": 0})["n"]
			)
			conn.execute(
				"INSERT OR IGNORE INTO message_receipts (event_id, continuity_id, state, reason, updated_at)"
				" SELECT e.event_id, ?, 'pulled', 'cursor_del_digest', ?"
				" FROM mission_events e WHERE e.to_continuity = ? AND e.event_seq <= ?",
				(soul, stamp, soul, ceiling),
			)
			conn.execute(
				"UPDATE message_receipts SET state = 'pulled', reason = 'cursor_del_digest', updated_at = ?"
				" WHERE continuity_id = ? AND state = 'handed_off'"
				" AND event_id IN (SELECT event_id FROM mission_events WHERE event_seq <= ?)",
				(stamp, soul, ceiling),
			)
			conn.commit()
			after = int(
				(conn.execute(
					"SELECT COUNT(*) AS n FROM message_receipts WHERE continuity_id = ?"
					" AND state = 'pulled' AND reason = 'cursor_del_digest'",
					(soul,),
				).fetchone() or {"n": 0})["n"]
			)
		return max(0, after - before)
	except Exception as e:
		logger.warning(f"[delivery] reconcile de pull falló: {e}")
		return 0


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
	event_id: Optional[str] = None,
) -> dict:
	"""Empuja al cuerpo vivo los eventos del alma que aún no tienen recibo.

	El **estado de transporte** no se escribe aquí: lo gobierna el outbox de
	neon-link. Este módulo escribe recibos: `handed_off` si el transporte tomó el
	aviso, `skipped` si era eco propio o el destinatario dijo no. Si el transporte
	falla, no escribe recibo y el evento queda para pull/reintento del outbox.
	"""
	from red_pill.core import soul_notify

	soul = str(continuity_id or "").strip()
	report: Dict[str, Any] = {
		"continuity_id": soul,
		"event_id": str(event_id or ""),
		"leg": "",
		"handed_off": [],
		"deferred": [],
		"skipped": [],
		"given_up": [],
	}
	if not soul:
		return report
	if soul_notify.notify_disabled():
		report["deferred"].append({"event_id": "*", "reason": "kill_switch"})
		return report

	events = pending_for_soul(soul, limit=limit, db_path=db_path, event_id=event_id)
	if not events:
		return report

	leg = str(originator or "").strip() or str(soul_notify.resolve_live_leg(soul) or "")
	report["leg"] = leg
	if not leg or ":" not in leg:
		for ev in events:
			report["deferred"].append({"event_id": ev["event_id"], "reason": "no_live_body"})
		return report

	provider, _, session_id = leg.partition(":")
	if provider not in INJECTION_POINTS or not session_id:
		for ev in events:
			report["deferred"].append({"event_id": ev["event_id"], "reason": f"no_injection_point:{provider}"})
		return report

	for ev in events:
		ev_id = str(ev.get("event_id") or "")
		if not ev_id:
			continue
		if str(ev.get("originator") or "") == leg:
			set_receipt(event_id=ev_id, continuity_id=soul, state=STATE_SKIPPED, reason="self_authored", db_path=db_path, now=now)
			report["skipped"].append({"event_id": ev_id, "reason": "self_authored"})
			continue
		blocked = _wake_verdict(ev, soul, leg, db_path=db_path)
		if blocked is not None and blocked.terminal:
			set_receipt(event_id=ev_id, continuity_id=soul, state=STATE_SKIPPED, reason=blocked.reason, db_path=db_path, now=now)
			report["skipped"].append({"event_id": ev_id, "reason": blocked.reason})
			continue
		if blocked is not None:
			report["deferred"].append({"event_id": ev_id, "reason": blocked.reason})
			continue
		text = build_event_nudge(ev)
		try:
			ok = bool(soul_notify.notify_soul(soul, text, originator=leg))
		except Exception as e:
			logger.warning(f"[delivery] transporte lanzó excepción en {ev_id[:12]}: {e}")
			ok = False
		if ok:
			trace = soul_notify.last_trace()
			set_receipt(
				event_id=ev_id,
				continuity_id=soul,
				state=STATE_HANDED_OFF,
				reason=f"handed_to_transport:{INJECTION_POINTS[provider]}" + (f" rastro={trace}" if trace else ""),
				db_path=db_path,
				now=now,
			)
			report["handed_off"].append({"event_id": ev_id, "type": ev.get("type"), "seq": ev.get("event_seq"), "trace": trace})
			continue
		# El outbox de neon-link reintenta; aquí solo se informa del fallo.
		why = f"transport_refused:{soul_notify.last_error() or 'desconocido'}"
		report["deferred"].append({"event_id": ev_id, "reason": why})
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
	# Cadena de mando (AD-090): un aviso de job dirigido a su propia alma puede
	# despertarla aunque el cuerpo del job no tenga fila en el registro. El job es
	# hijo del alma que lo lanzó; sin esta regla el aviso quedaría en pull y el
	# callback no despertaría a nadie. Solo aplica a avisos auto-dirigidos con
	# origen `job:`; los controles de entrada del destinatario (refuse/hold) se
	# respetan antes de conceder el paso.
	originator = str(ev.get("originator") or "")
	if ev.get("continuity_id") == soul and originator.startswith("job:"):
		blocked = wake_policy.inbound_blocked(soul, originator=leg, db_path=db_path)
		if blocked:
			return wake_policy.Decision(False, blocked)
		return None
	try:
		with _connect(db_path) as conn:
			recipient = _actor_for(conn, soul, originator=leg)
			sender = _actor_for(conn, "", originator=originator, by_leg=True)
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
			conn.execute(_RECEIPT_DDL)
			rows = conn.execute("SELECT state, COUNT(*) AS n FROM message_receipts WHERE continuity_id = ? GROUP BY state", (soul,)).fetchall()
		for row in rows:
			out[str(row["state"])] = int(row["n"])
	except Exception as e:
		logger.debug(f"[delivery] resumen falló: {e}")
	return out
