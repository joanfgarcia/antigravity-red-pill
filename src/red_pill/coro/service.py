"""Servicio del coro — las acciones de `coro_api` (AD-095).

Qué resuelve
------------
Una sola puerta para el tablón y la correspondencia entre almas:

| acción | qué hace |
|---|---|
| `post`   | nota al tablón de MI misión (sin destinatario, no despierta) |
| `send`   | mensaje dirigido a un alma: `notify` / `ask` / `reply` / `park` |
| `inbox`  | lo que me espera (global, por alma) con su estado |
| `ack`    | leído: cierra el mensaje |
| `fetch`  | eventos del tablón desde mi cursor (pull) |
| `board`  | sala de guerra: sesiones vivas o misiones |
| `object` | objeción D23 sobre una nota (abre D-obj) |

Reglas que este módulo **no** se salta
--------------------------------------
- **Identidad del canal, no del modelo.** La sesión la resuelve el servidor
(`caller_session`); un `to`/`from` declarado por el modelo no acredita nada. La
autoría del evento la estampa el canal (AD-056).
- **La misión del evento es la mía.** Un mensaje a otra alma vive en MI tablón con
`to_continuity`; nunca se escribe en la misión ajena (anti-spoof).
- **Rebote = `park`, no silencio.** Si el destinatario no puede recibir ahora, el
mensaje queda `queued` y lo recoge su `inbox` al reencarnar.
- **Despertar no es gratis.** El push pasa por la política (`wake_policy`), no por
la buena fe del emisor (D-07); el emisor elige verbo, no interrupción (D-03).
- **Un mensaje es DATO** (T3/D-09): se delimita, se marca su procedencia y no se
le da autoridad sobre las reglas del receptor.

Lo que NO hace (y hay que decir)
--------------------------------
- El cuerpo es la `summary` del evento: **800 caracteres** (tope del tablón). La
ley del recado completa (64 KB + Apartado Postal) llega con el buzón único (S2);
hoy un mensaje más largo se rechaza, no se trunca.
- `dlq`/`replay` no existen aún: son del broker (S2). No se registran para no
ofrecer una acción que miente.
- El contador de saltos vive aquí; la **huella anti-bucle** es del transporte
(D-01: el prompt no es un candado) y llega con el adaptador.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from red_pill.coro import protocol
from red_pill.session.store import SessionRegistry, sanitize_inline


class CoroError(Exception):
	"""Error de uso: se devuelve al agente como texto, no como excepción."""


# ── Identidad del llamante ───────────────────────────────────────────────────


def _require_body(session: Dict[str, Any]) -> str:
	originator = str(session.get("originator") or "").strip()
	if ":" not in originator:
		raise CoroError("sin cuerpo compuesto (bridge/env); deny-by-default (fail-closed).")
	return originator


def _require_mission(session: Dict[str, Any]) -> str:
	mission = str(session.get("mission_id") or "").strip()
	if not mission:
		raise CoroError("sin misión resuelta; no se publica.")
	return mission


def _require_soul(session: Dict[str, Any]) -> str:
	soul = str(session.get("continuity_id") or "").strip()
	if not soul:
		raise CoroError("sin alma resuelta (el registro no tiene tu continuity_id).")
	return soul


def _new_thread() -> str:
	return "E-" + uuid.uuid4().hex[:6]


# ── Acciones ─────────────────────────────────────────────────────────────────


async def post(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Nota al tablón de MI misión. Sin destinatario no hay correspondencia."""
	originator = _require_body(session)
	mission = _require_mission(session)
	requested = str(payload.get("mission_id") or "").strip()
	if requested and requested != mission:
		raise CoroError(f"la misión de tu sesión es {mission!r}, no {requested!r}.")
	requested_campaign = str(payload.get("campaign_id") or "").strip()
	if requested_campaign and requested_campaign != str(session.get("campaign_id") or ""):
		raise CoroError(f"la campaña de tu sesión es {session.get('campaign_id')!r}, no {requested_campaign!r}.")
	sealed = payload.get("sealed", False)
	if not isinstance(sealed, bool):
		raise CoroError("`sealed` debe ser boolean (true/false).")
	registry = SessionRegistry()
	event = registry.add_event(
		event_type=str(payload.get("type") or "intent_updated"),
		mission_id=mission,
		campaign_id=session.get("campaign_id"),
		continuity_id=session.get("continuity_id"),
		originator=originator,
		global_turn=registry.get_max_global_turn(),
		summary=str(payload.get("summary") or ""),
		ref=payload.get("ref"),
		sealed=sealed,
	)
	tag = " [sealed]" if event.get("sealed") else ""
	return f"[CORO post] {event['type']} · {event['mission_id']} · seq={event['event_seq']} · event={event['event_id']}{tag}"


async def send(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Mensaje dirigido a un alma. El verbo lo declara el emisor (D-02)."""
	originator = _require_body(session)
	mission = _require_mission(session)
	me = _require_soul(session)
	verb = str(payload.get("verb") or "").strip().lower()
	if verb not in protocol.VERBS:
		raise CoroError(f"verbo desconocido: {payload.get('verb')!r} (usa {', '.join(protocol.VERBS)}).")
	body = str(payload.get("body") or payload.get("summary") or "").strip()
	if not body:
		raise CoroError("`body` requerido.")
	registry = SessionRegistry()
	reply_to = str(payload.get("reply_to") or "").strip()
	parent: Optional[dict] = None
	if reply_to:
		parent = registry.get_event(reply_to)
		if not parent or parent.get("type") != "message":
			raise CoroError(f"`reply_to` no apunta a un mensaje: {reply_to!r}.")
	if verb == protocol.VERB_REPLY and not parent:
		raise CoroError("`reply` requiere `reply_to` (el mensaje que contestas).")
	if parent and parent.get("to_continuity") and parent.get("to_continuity") != me:
		raise CoroError("ese mensaje no era para ti: no puedes contestarlo.")
	target = str(payload.get("to") or (parent or {}).get("continuity_id") or "").strip()
	if not target:
		raise CoroError("`to` requerido (continuity_id del alma destinataria).")
	if target == me:
		raise CoroError("te estarías escribiendo a ti misma; usa `post` para tu tablón.")
	known = registry.get_by_continuity(target)
	if not known:
		raise CoroError(
			"alma desconocida: no hay ningún cuerpo registrado con ese continuity_id "
			"(fail-closed: no se adivina a quién iba). Mira `board` para ver las almas vivas."
		)

	# Salto: la réplica NO consume (D-02); solo salta el mensaje iniciado.
	ceiling = protocol.hop_max()
	value = str(payload.get("value") or protocol.VALUE_NOW).strip().lower()
	if value not in protocol.VALUES:
		raise CoroError(f"`value` desconocido: {value!r} (usa now|seed).")
	expects = payload.get("expects_reply")
	if expects is None:
		expects = verb == protocol.VERB_ASK
	if parent:
		thread = str(parent.get("thread_id") or payload.get("thread_id") or _new_thread())
		hop = int(parent.get("hop") or 0)
	else:
		thread = str(payload.get("thread_id") or _new_thread())
		hop = int(payload.get("hop") or 0)
		if hop > ceiling:
			raise CoroError(f"techo de saltos alcanzado ({hop} > {ceiling}): usa `post` o cierra el hilo.")
	expires = time.time() + protocol.budget_s(verb, value)

	event = registry.add_event(
		event_type="message",
		mission_id=mission,
		campaign_id=session.get("campaign_id"),
		continuity_id=me,
		originator=originator,
		global_turn=registry.get_max_global_turn(),
		summary=body,
		ref=reply_to or None,
		sealed=False,
		to_continuity=target,
		verb=verb,
		thread_id=thread,
		hop=hop,
		hop_max=ceiling,
		expects_reply=bool(expects),
		value_class=value,
		expires_at=expires,
	)

	state, reason = "queued", ""
	if verb in protocol.WAKE_VERBS:
		state, reason = _push(target)

	reply_note = " · respuesta: SÍ" if expects else ""
	why = f" · {reason}" if reason else ""
	return (
		f"[CORO send] {verb} → {protocol.soul_mark(target)} · hilo {thread} · salto {hop}/{ceiling} · "
		f"estado={state}{reply_note} · expira en {protocol.budget_s(verb, value) / 86400:.0f}d · "
		f"msg={event['event_id']} · seq={event['event_seq']}{why}"
	)


def _push(target: str) -> tuple[str, str]:
	"""Intenta el push al alma. Devuelve (estado, motivo). Nunca lanza."""
	try:
		from red_pill.session import delivery

		report = delivery.deliver_events(target, holder="coro_send")
	except Exception as e:  # el push es un lujo; el pull es la entrega real
		return "queued", f"push_failed: {e}"
	if report.get("delivered"):
		return "delivered", ""
	reasons = [
		str(item.get("reason") or "")
		for bucket in ("deferred", "skipped", "given_up")
		for item in (report.get(bucket) or [])
	]
	reason = ", ".join(r for r in reasons if r) or "sin_cuerpo"
	return "queued", f"park ({reason})"


async def inbox(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Lo que me espera: mensajes dirigidos a mi alma, de cualquier misión."""
	me = _require_soul(session)
	registry = SessionRegistry()
	limit = max(1, min(int(payload.get("limit") or 20), 100))
	since = int(payload.get("since_seq") or 0)
	events = registry.fetch_inbox(me, limit=limit, since_seq=since)
	if not events:
		return "[CORO inbox] sin mensajes pendientes."
	from red_pill.session import delivery

	lines = [f"--- INBOX {protocol.soul_mark(me)} ({len(events)}) ---"]
	for ev in events:
		row = delivery.get_delivery(ev["event_id"], me) or {}
		state = _friendly_state(str(row.get("state") or ""))
		header = protocol.envelope(
			verb=str(ev.get("verb") or "notify"),
			thread_id=ev.get("thread_id"),
			hop=ev.get("hop"),
			hop_max_value=ev.get("hop_max"),
			expects_reply=ev.get("expects_reply"),
			value=ev.get("value_class"),
			from_mark=protocol.soul_mark(ev.get("continuity_id")),
			mission_id=ev.get("mission_id"),
			expires_at=ev.get("expires_at"),
		)
		lines.append(f"[{ev.get('event_seq')}] {header}")
		lines.append(f"  estado={state} · {sanitize_inline(ev.get('summary'), 800)}")
		if ev.get("ref"):
			lines.append(f"  re: {sanitize_inline(ev.get('ref'), 120)}")
	return "\n".join(lines)


def _friendly_state(raw: str) -> str:
	"""Estados del protocolo (§5) sobre los del registro de entrega."""
	if raw == "read":
		return "read"
	if raw == "delivered":
		return "delivered"
	if raw in {"pulled", "in_flight"}:
		return "delivered" if raw == "pulled" else "queued"
	return "queued"


async def ack(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Marca leído un mensaje de mi inbox (detiene su vida útil)."""
	me = _require_soul(session)
	event_id = str(payload.get("event_id") or "").strip()
	if not event_id:
		raise CoroError("`event_id` requerido.")
	event = SessionRegistry().get_event(event_id)
	if not event or event.get("to_continuity") != me:
		raise CoroError("ese mensaje no está en tu inbox.")
	from red_pill.session import delivery

	ok = delivery.mark_read(event_id, me)
	return f"[CORO ack] {event_id[:12]} · {'leído' if ok else 'no se pudo marcar'}"


async def fetch(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Eventos del tablón desde mi cursor (pull; el push solo adelanta)."""
	_require_body(session)
	mission = _require_mission(session)
	target = str(payload.get("mission_id") or mission).strip()
	if target != mission:
		raise CoroError(f"cross-misión denegado (deny-by-default): {sanitize_inline(target)!r}.")
	events = SessionRegistry().fetch_events(
		target,
		since_seq=int(payload.get("since_seq") or 0),
		types=payload.get("types"),
		limit=int(payload.get("limit") or 50),
		viewer_originator=session.get("originator"),
		viewer_continuity_id=session.get("continuity_id"),
		include_hidden=os.getenv("REDPILL_OPERATOR") == "1",
	)
	if not events:
		return f"[CORO fetch] {sanitize_inline(target)}: sin novedades."
	lines = [f"--- EVENTOS {sanitize_inline(target)} ({len(events)}) ---"]
	for event in events:
		ref = f" · {event['ref']}" if event.get("ref") else ""
		seal = " [sealed]" if event.get("sealed") else ""
		status = str(event.get("note_status") or "visible")
		tag = f" [{status}]" if status in {"flagged", "hidden", "retracted"} else ""
		open_decisions = int(event.get("open_decisions") or 0)
		if open_decisions > 0:
			tag += f" [disputed:{open_decisions}]"
		lines.append(f"[{event.get('event_seq', 0)}] {event['type']}{tag}: {event['summary']}{ref}{seal}")
	return "\n".join(lines)


async def board(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Sala de guerra. `scope=sesiones` (cuerpos vivos) o `misiones` (agrupado)."""
	scope = str(payload.get("scope") or "sesiones").strip().lower()
	if scope in {"misiones", "missions", "mission"}:
		return _board_missions()
	return _board_sessions(session, payload)


def _board_missions() -> str:
	from red_pill.core.session_index import build_board, render_board, write_index

	board_obj = build_board()
	write_index(board_obj)
	return render_board(board_obj)


def _board_sessions(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	from red_pill.core.session_index import _registry_ttl_s

	registry = SessionRegistry()
	global_turn = registry.get_max_global_turn()
	rows = registry.list_sessions(limit=max(1, min(int(payload.get("limit") or 50), 200)))
	my = registry.get_by_originator(session["originator"]) if session.get("originator") else None
	my_last = int((my or {}).get("last_seen_global_turn") or 0)
	delta = max(0, global_turn - my_last)
	include_git = bool(payload.get("include_git_status"))
	ttl = _registry_ttl_s()
	now = time.time()
	lines = [
		f"--- CORO: global_turn={global_turn} · tú={sanitize_inline(session.get('mission_id'), 120)} · "
		f"last_seen={my_last} · delta={delta} ---"
	]
	shown = 0
	for row in rows:
		if row.get("ttl_state") == "expired":
			continue
		if (now - float(row.get("updated_at") or 0.0)) > ttl:
			continue
		last = int(row.get("last_seen_global_turn") or 0)
		parts = [
			f"[{sanitize_inline(row.get('provider'), 40)}] {sanitize_inline(row.get('session_id'), 60)}",
			f"alma={sanitize_inline(row.get('continuity_id'), 12)}",
			f"misión={sanitize_inline(row.get('mission_id'), 80)}",
		]
		if row.get("campaign_id"):
			parts.append(f"campaña={sanitize_inline(row.get('campaign_id'), 80)}")
		parts.append(f"rol={sanitize_inline(row.get('role'), 20)}")
		parts.append(f"delta={max(0, global_turn - last)}")
		parts.append(f"ttl={sanitize_inline(row.get('ttl_state'), 20)}")
		try:
			aff = json.loads(row.get("affinity_json") or "[]")
		except Exception:
			aff = []
		if isinstance(aff, list) and aff:
			parts.append("afinidad=" + sanitize_inline(",".join(str(a) for a in aff), 120))
		if include_git:
			if row.get("branch"):
				parts.append(f"rama={sanitize_inline(row.get('branch'), 80)}")
			if row.get("worktree"):
				parts.append(f"worktree={sanitize_inline(row.get('worktree'), 120)}")
			if row.get("head_commit"):
				parts.append(f"head={sanitize_inline(row.get('head_commit'), 12)}")
		lines.append(" · ".join(parts))
		shown += 1
	if shown == 0:
		lines.append("(sin sesiones recientes)")
	return "\n".join(lines)


async def objection(session: Dict[str, Any], payload: Dict[str, Any]) -> str:
	"""Objeción D23 sobre una nota de mi misión (abre una D-obj)."""
	originator = _require_body(session)
	mission = _require_mission(session)
	continuity = _require_soul(session)
	target = str(payload.get("target_event_id") or "").strip()
	if not target:
		raise CoroError("`object` requiere `target_event_id`.")
	registry = SessionRegistry()
	subject = registry.get_event(target)
	if not subject:
		raise CoroError("la nota objetivo no existe.")
	if subject["mission_id"] != mission:
		raise CoroError("objeción cross-misión no soportada en v0 (misma misión que la nota).")
	if subject.get("sealed"):
		raise CoroError("no se objeta una nota sealed (v0).")
	if registry.get_note_status(target) in {"hidden", "retracted"}:
		raise CoroError("no se objeta una nota hidden/retracted.")
	decision = registry.open_decision(
		subject_event_id=target,
		claim=str(payload.get("claim") or payload.get("summary") or ""),
		created_by=continuity,
		mission_id=mission,
		evidence=str(payload.get("evidence") or ""),
		severity=str(payload.get("severity") or "low"),
		proposed_action=str(payload.get("proposed_action") or "flag"),
	)
	if not decision.get("created"):
		return (
			f"[CORO object] ya existe D-obj {decision['decision_id'][:12]} "
			f"state={decision['state']} note={target[:12]}"
		)
	event = registry.add_event(
		event_type="objection",
		mission_id=mission,
		campaign_id=session.get("campaign_id"),
		continuity_id=continuity,
		originator=originator,
		global_turn=registry.get_max_global_turn(),
		summary=str(payload.get("summary") or payload.get("claim") or ""),
		ref=decision["decision_id"],
		sealed=False,
	)
	op = " [requiere Operador]" if decision.get("requires_operator") else ""
	review_job = None
	mode = "off"
	try:
		from red_pill.session.d23_review import enqueue_review, review_mode

		mode = review_mode()
		if mode != "off":
			review_job = enqueue_review(decision, subject, mode)
	except Exception:
		review_job = None
	extra = f" · review_job={review_job}" if review_job else ""
	extra += f" · mode={mode}" if mode != "off" else ""
	return (
		f"[CORO object] decision={decision['decision_id']} · state={decision['state']}{op} · "
		f"note={target} · event={event['event_id']} · seq={event['event_seq']}{extra}"
	)
