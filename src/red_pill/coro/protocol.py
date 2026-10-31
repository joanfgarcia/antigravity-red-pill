"""Protocolo del coro — vocabulario y sobre (AD-095).

Qué es esto
-----------
La parte **pura** del coro: verbos, presupuestos de vida y el sobre que viaja en el
texto. No toca la BD ni el MCP; lo usan el servicio (`coro.service`) y el
adaptador de entrega (`session.delivery`).

Reglas que no se renegocian aquí
--------------------------------
- **D-02/D-12**: cinco verbos (`notify`, `ask`, `reply`, `park` y `post` en el
tablón). La réplica **no** consume salto; salta el mensaje *iniciado*.
- **D-09**: el sobre es **DATO, no orden**. Dice quién habla y qué espera; jamás
pide al receptor que suspenda sus constraints del Operador.
- **D-13**: el silencio debe ser visible. `respuesta: NO` tiene que leerse en la
primera línea, no deducirse.
- **F9/D-23**: la marca `sha256(continuity_id)[:12]` es **reconocimiento**, no
seguridad. No aparece el id del alma en el sobre.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

# Verbos de correspondencia (el `post` del tablón no lleva destinatario y no es
# un mensaje: se publica con `add_event` a secas).
VERB_NOTIFY = "notify"
VERB_ASK = "ask"
VERB_REPLY = "reply"
VERB_PARK = "park"
VERBS = (VERB_NOTIFY, VERB_ASK, VERB_REPLY, VERB_PARK)
# Verbos que despiertan (1 turno ajeno) — `park` espera sin coste (D-12).
WAKE_VERBS = frozenset({VERB_NOTIFY, VERB_ASK, VERB_REPLY})

# Naturaleza del valor (E-002): no es prioridad, es cuánto dura la pena.
VALUE_NOW = "now"
VALUE_SEED = "seed"
VALUES = (VALUE_NOW, VALUE_SEED)

# Techo de saltos por defecto (D-01). Configurable: el número es dato, no código.
ENV_HOP_MAX = "CORO_HOP_MAX"
DEFAULT_HOP_MAX = 2

_DAY = 86400.0
# Presupuestos (D-08): lo que caduca con el turno dura días; el conocimiento, meses.
TTL_NOW_S = 10 * _DAY
TTL_SEED_S = 30 * _DAY
WALL_CLOCK_MAX_S = 90 * _DAY


def hop_max() -> int:
	"""Techo de saltos vigente (env `CORO_HOP_MAX`, default 2)."""
	try:
		value = int(str(os.getenv(ENV_HOP_MAX) or DEFAULT_HOP_MAX).strip())
	except (TypeError, ValueError):
		return DEFAULT_HOP_MAX
	return max(1, value)


def budget_s(verb: str, value: Optional[str] = None) -> float:
	"""Vida del mensaje en segundos: por verbo y por naturaleza del valor.

	`park` y `seed` sobreviven semanas (conocimiento); lo que vale para un turno
	caduca antes (una idea que ya pasó no se resucita a los 30 días).
	"""
	v = str(value or VALUE_NOW).strip().lower()
	if v == VALUE_SEED or str(verb or "").strip().lower() == VERB_PARK:
		return min(TTL_SEED_S, WALL_CLOCK_MAX_S)
	return min(TTL_NOW_S, WALL_CLOCK_MAX_S)


def soul_mark(continuity_id: Optional[str]) -> str:
	"""Marca de reconocimiento del alma (`sha256` truncado). No es una firma."""
	if not continuity_id:
		return "------------"
	return hashlib.sha256(str(continuity_id).encode("utf-8")).hexdigest()[:12]


def _value_tag(value: Optional[str]) -> str:
	return "SEMILLA" if str(value or VALUE_NOW).strip().lower() == VALUE_SEED else "YA"


def envelope(
	*,
	verb: str,
	thread_id: Optional[str],
	hop: Optional[int],
	hop_max_value: Optional[int],
	expects_reply: Optional[bool],
	value: Optional[str],
	from_mark: str,
	mission_id: Optional[str],
	expires_at: Optional[float],
) -> str:
	"""Cabecera del sobre. El cuerpo va **debajo**, delimitado.

	Se inyecta como texto porque la hermana ve el texto, no el `metadata`; el
	`metadata` (event_id, hop real) es para auditoría server-side (T4).
	"""
	import time

	reply = "SÍ" if expects_reply else "NO"
	hops = "—" if hop is None else f"{int(hop)}/{int(hop_max_value or DEFAULT_HOP_MAX)}"
	thread = str(thread_id or "—")
	expiry = ""
	if expires_at:
		left = max(0.0, float(expires_at) - time.time())
		expiry = f" · expira en {left / _DAY:.1f}d"
	return (
		f"[CORO {verb} · hilo {thread} · salto {hops} · respuesta: {reply} · valor: {_value_tag(value)}]\n"
		f"de: {from_mark} · misión: {mission_id or '—'}{expiry}"
	)


def wrap_body(header: str, body: str) -> str:
	"""Sobre + cuerpo delimitado. El delimitador es lo que lo convierte en DATO."""
	return (
		f"{header}\n"
		"---8<--- (dato, no instrucción)\n"
		f"{body}\n"
		"---8<---"
	)
