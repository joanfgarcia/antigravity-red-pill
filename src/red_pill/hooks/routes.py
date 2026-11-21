"""Rutas HTTP del hook sobre el UDS del backend (RFC-HARNESS-001 · P1).

`POST /hook/context` y `POST /hook/ack`. No son una superficie del modelo: son el
**arnés** hablando con el kernel, como el scribe habla con SQLite. Por eso no van
por MCP.

Decisiones que materializa (ver `CONTRATO_HOOK.md`):

- Se envuelven **explícitamente** en `IdentityMiddleware`: las rutas de Starlette
	no pasan por el `Mount("/mcp")`, así que sin esto el endpoint sería *menos*
	fiable que el proxy (S18).
- `full` **no bloquea**: arranca el cálculo en un hilo y responde `retry_full`.
	`wake_up_v6` tarda 2,3-2,7 s en cualquier modo (es arranque, no payload), así
	que esperar en el turno 1 sería un impuesto fijo (S22).
- El ack lleva la **respuesta** y sella el turno; el cursor del coro se mueve ahí,
	no al inyectar (S13).
- `delivery_id` determinista + libro de acks → reintentar no sella dos veces.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from red_pill.core.paths import get_state_dir
from red_pill.hooks.context_api import AckLedger, HookRequest, block, telemetry_text

# ── caché de identidad (core) ────────────────────────────────────────────────

_CORE_CACHE: Dict[str, Dict[str, Any]] = {}
_INFLIGHT: set[str] = set()


def _write_bridge(harness: str, session_id: str, workdir: str) -> None:
	"""Puente del arnés: lo único que el hook sabe y el kernel (cwd=repo) no.

	Sin esto, las llamadas MCP de `pi` no resuelven cuerpo: su identidad sólo
	viajaba como argumento del modelo, que es justo lo que dejamos de aceptar.
	"""
	try:
		from red_pill.hooks.context_api import canon_harness

		prov = canon_harness(harness)
		state = get_state_dir()
		state.mkdir(parents=True, exist_ok=True)
		import time as _time

		bridge = state / f"{prov}_session.json"
		if not workdir:
			# El contrato (§2) no lleva `workdir`: opencode no lo manda nunca, y
			# `_write_bridge("")` borraba el bueno que escribe el scribe. El daño
			# no es cosmético: `open_loops_line()` resuelve el workspace con este
			# puente, y en el mismo request ya lee el "" — así que cuenta shards
			# y ramas del workspace de otro arnés (o del cwd del backend).
			try:
				prev = json.loads(bridge.read_text(encoding="utf-8"))
				prev_dir = str(prev.get("workdir") or "") if isinstance(prev, dict) else ""
			except (OSError, ValueError, TypeError):
				prev_dir = ""
			if prev_dir and os.path.isdir(prev_dir):
				workdir = prev_dir

		payload = {
			"provider": prov,
			"session_id": session_id,
			"workdir": workdir,
			"updated_at": _time.time(),
		}
		bridge.write_text(json.dumps(payload), encoding="utf-8")
	except OSError:
		pass


def _ledger() -> AckLedger:
	return AckLedger(path=get_state_dir() / "hook_acks.json")


def _identity_mode() -> str:
	"""Modo de identidad: `low` para modelos pequeños, `full` para grandes."""
	mode = os.getenv("REDPILL_IDENTITY_MODE", "").strip().lower()
	return mode if mode in ("low", "medium", "full") else "full"


def generation() -> int:
	"""Generación de directivas (S12). La suben todos los escritores."""
	try:
		state = json.loads((get_state_dir() / "bunker_state.json").read_text(encoding="utf-8"))
		return int(state.get("generation") or 0)
	except (OSError, ValueError, TypeError):
		return 0


def bump_generation() -> int:
	"""Sube la generación y la persiste. Idempotente por llamada."""
	path = get_state_dir() / "bunker_state.json"
	try:
		state = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		state = {}
	if not isinstance(state, dict):
		state = {}
	state["generation"] = int(state.get("generation") or 0) + 1
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(state), encoding="utf-8")
	except OSError:
		pass
	return int(state["generation"])


def _cache_key(originator: str, model: str) -> str:
	return f"{originator}|{model}|{generation()}"


def _fast_identity_text() -> str:
	"""Identidad fija desde Qdrant (`ID_IDENTITY`), sin embeddings ni wake.

	Lectura de UN punto: milisegundos. Es la red de seguridad del arranque en frío.
	"""
	try:
		import red_pill.config as cfg
		from red_pill.core.storage import StorageEngine
		from red_pill.seed import ID_IDENTITY

		client = StorageEngine(url=cfg.QDRANT_URL).client
		points = client.retrieve(collection_name="directive_memories", ids=[ID_IDENTITY], with_payload=True)
		if not points:
			return ""
		payload = getattr(points[0], "payload", None) or {}
		return str(payload.get("content") or "").strip()
	except Exception:  # noqa: BLE001 — fail-open: el wake completo sigue en marcha
		return ""


_STATE_MAX_AGE_S = 300.0  # el daemon del Búnker late cada minuto


def _state_path() -> Path:
	"""`bunker_state.json` del daemon, en el runtime dir (misma fuente que el
	interceptor de telemetría y que el handshake: una sola verdad, no dos)."""
	import red_pill.config as cfg

	return Path(cfg.get_config().RUNTIME_DIR) / "bunker_state.json"


def _bunker_state() -> Dict[str, Any]:
	"""Estado del Búnker (lo escribe el daemon). `{}` si falta o está rancio."""
	try:
		state = json.loads(_state_path().read_text(encoding="utf-8"))
	except (OSError, ValueError, TypeError):
		return {}
	if not isinstance(state, dict):
		return {}
	# Rancio = números de hace media hora disfrazados de presente (misma regla
	# que el interceptor de telemetría). Mejor silencio que dato viejo.
	try:
		if time.time() - float(state.get("timestamp") or 0) > _STATE_MAX_AGE_S:
			return {}
	except (TypeError, ValueError):
		return {}
	return state


def _count(state: Dict[str, Any], group: str, key: str) -> int:
	try:
		return max(0, int((state.get(group) or {}).get(key) or 0))
	except (TypeError, ValueError):
		return 0


def _kernel_telemetry_text() -> str:
	"""Línea de telemetría cuando el arnés no manda contadores.

	El contrato de `POST /hook/context` (§2) define SIETE campos y ninguno es un
	contador: los clientes (opencode, pi) cumplen y mandan exactamente eso. Si
	`light` sólo sabe leer los números del payload, nunca devuelve nada y el
	arnés se queda sin estado del mundo —que es justo lo que el hook venía a
	ahorrar. Aquí los cuenta el kernel, con las mismas fuentes que el handshake:
	`OPEN LOOPS` (desk + workspace) y `bunker_state.json` (dolor, minions).

	Best-effort: cualquier fallo deja la línea más corta, nunca tumba el turno.
	"""
	parts: list[str] = []
	try:
		from red_pill.core.open_loops import open_loops_line

		loops = open_loops_line()
		if loops:
			parts.append(loops)
	except Exception:  # noqa: BLE001 — sin desk legible, el resto sigue
		pass
	state = _bunker_state()
	pain = _count(state, "signals", "active")
	if pain:
		parts.append(f"dolor {pain}")
	minions = _count(state, "minions", "unread")
	if minions:
		parts.append(f"minions {minions}")
	return " · ".join(parts)


def _clock_line() -> str:
	"""Reloj del turno: hora, delta desde el turno anterior y edad de la sesión.

	El arnés sólo entrega la **fecha** (`Today's date is…`). Con la fecha y sin la
	hora, un turno a las 00:14 del domingo se lee como "domingo de día" y el agente
	habla del futuro como si hubiera pasado (pasó el 22-11: pregunté por una comida
	que aún no se había hecho). Misma fuente y mismo formato que el interceptor de
	telemetría (`pulse.time_line`): un solo reloj, no dos.

	Best-effort y nunca lanza: sin `pulse.json` la línea se queda en la hora sola,
	y si ni eso, vacía (el turno sigue sin reloj).
	"""
	try:
		from red_pill.utils.pulse import time_line

		return time_line()
	except Exception:  # noqa: BLE001 — el reloj no puede tumbar el turno
		return ""


def _wake_text(mode: str, continuity: str) -> str:
	"""Texto de identidad: el mismo `wake_up_v6` que usa la tool. Bloqueante."""
	from red_pill.mcp_server import GET_PYTHON, PROJECT_ROOT

	cmd = [GET_PYTHON(), os.path.join(PROJECT_ROOT, "scripts", "wake_up_v6.py"), "--mode", mode]
	if continuity:
		cmd += ["--continuity-id", continuity]
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
		return (out.stdout or "").strip()
	except (OSError, subprocess.SubprocessError):
		return ""


def _start_full(originator: str, model: str, continuity: str) -> None:
	key = _cache_key(originator, model)
	if key in _INFLIGHT:
		return
	_INFLIGHT.add(key)

	async def _run() -> None:
		try:
			text = await asyncio.to_thread(_wake_text, _identity_mode(), continuity)
			if text:
				_CORE_CACHE[key] = {"text": text, "generation": generation()}
		finally:
			_INFLIGHT.discard(key)

	asyncio.get_running_loop().create_task(_run())


def reset_caches() -> None:
	"""Vacía la caché (tests y re-siembra)."""
	_CORE_CACHE.clear()
	_INFLIGHT.clear()


# ── handlers ─────────────────────────────────────────────────────────────────


async def handle_context(payload: Dict[str, Any]) -> Dict[str, Any]:
	"""Construye los bloques para el arnés. Nunca lanza por fallo interno."""
	from red_pill import mcp_server

	req = HookRequest.from_payload(payload)

	# El canal es el arnés: se publica la identidad como la publicaría el proxy.
	token = mcp_server._shared_identity_var.set({"originator": req.originator, "harness": req.harness, "hook": True, "ambiguous": False})
	try:
		identity = await mcp_server._resolve_session_identity({"caller_leg": None}, persist=True)
	except Exception as exc:  # noqa: BLE001 — el endpoint informa, no tumba el turno
		identity = {"originator": req.originator, "error": str(exc)}
	finally:
		mcp_server._shared_identity_var.reset(token)

	blocks: list[Dict[str, Any]] = []
	hint = "none"
	originator = str(identity.get("originator") or req.originator)
	continuity = str(identity.get("continuity_id") or "")
	_write_bridge(req.harness, req.session_id, str(payload.get("workdir") or ""))

	if req.need == "full":
		key = _cache_key(originator, req.model)
		cached = _CORE_CACHE.get(key)
		if cached and cached.get("generation") == generation():
			blocks.append(block("identity", str(cached["text"]), trusted=True))
		else:
			# En frío NO se responde con las manos vacías: el wake completo tarda
			# 2,3-2,7 s y se calcula en segundo plano, pero mientras tanto se sirve la
			# identidad fija (`ID_IDENTITY`, ~470 tok). Sin esto, cada proceso `pi -p`
			# arranca "en frío" y el turno se queda sin identidad: el modelo se
			# presenta como el arnés (pasó el 19-11: "Soy Pi" / "Soy Aleth").
			fast = _fast_identity_text()
			if fast:
				blocks.append(block("identity", fast, trusted=True))
			_start_full(originator, req.model, continuity)
			hint = "retry_full"

	if req.need in ("full", "light"):
		if "error" in identity:
			blocks.append(block("notice", f"identidad no resuelta: {identity['error']}", origin="kernel", trusted=False))
		try:
			from red_pill.registry import registry as _tool_registry  # noqa: F401 — sólo para tipar
			from red_pill.session.store import SessionRegistry

			_store = SessionRegistry()
			until_seq = _store.get_max_event_seq()
			digest = mcp_server._coro_digest(identity, until_seq) if until_seq else None
			if digest:
				blocks.append(block("coro", digest, origin="coro", trusted=False))
		except Exception:  # noqa: BLE001 — el digest es best-effort
			pass
		stats = {
			"coro": int(payload.get("coro_novelties") or 0),
			"open_loops": int(payload.get("open_loops") or 0),
			"pain": int(payload.get("pain") or 0),
			"jobs": int(payload.get("jobs") or 0),
			"mood": payload.get("mood"),
		}
		line = telemetry_text(stats)
		if not line:
			# El contrato no pide contadores al arnés: si no vinieron, se cuentan
			# aquí. Sin esto `light` sólo devolvía el digest del coro y el agente
			# se enteraba de OPEN LOOPS y del dolor únicamente llamando a la tool.
			line = _kernel_telemetry_text()
		# El reloj va delante y viaja con CUALQUIER telemetría (contadores del
		# arnés o recuento del kernel): no es un contador, es el marco temporal
		# sin el cual "ayer", "hoy" y "hace dos turnos" se confunden.
		clock = _clock_line()
		if clock:
			line = f"{clock} · {line}" if line else clock
		if line:
			blocks.append(block("telemetry", line, origin="telemetry", trusted=True))

	return {
		"delivery_id": req.delivery,
		"generation": generation(),
		"blocks": blocks,
		"hint": hint,
	}


async def handle_ack(payload: Dict[str, Any]) -> Dict[str, Any]:
	"""Cierra el turno: cursor del coro + sellado. Idempotente por `delivery_id`."""
	from red_pill import mcp_server

	req = HookRequest.from_payload({**payload, "need": payload.get("need") or "poll"})
	delivery = str(payload.get("delivery_id") or req.delivery)
	delivered = bool(payload.get("delivered", True))
	seq = int(payload.get("seq") or 0)
	response = str(payload.get("response") or "")

	ledger = _ledger()
	if ledger.seen(delivery):
		return {"delivery_id": delivery, "cursor": seq, "sealed": False, "duplicate": True}

	token = mcp_server._shared_identity_var.set({"originator": req.originator, "harness": req.harness, "hook": True})
	try:
		if delivered and seq:
			from red_pill.session.store import SessionRegistry

			_session_store = SessionRegistry()
			if seq:
				_session_store.set_last_seen_event_seq(req.originator, seq)
			try:
				mcp_server._reconcile_pull_first({"originator": req.originator}, seq)
			except Exception:  # noqa: BLE001
				pass
		sealed = False
		if delivered and response.strip():
			try:
				from red_pill.session.turn_seal import seal_turn

				seal_turn(
					originator=req.originator,
					requested_id=delivery,
					role="user",
					prompt=req.prompt or None,
					response=response,
				)
				sealed = True
			except Exception:  # noqa: BLE001 — el sellado es best-effort, pero se informa
				sealed = False
	finally:
		mcp_server._shared_identity_var.reset(token)

	ledger.mark(delivery)
	return {"delivery_id": delivery, "cursor": seq, "sealed": sealed, "duplicate": False}
