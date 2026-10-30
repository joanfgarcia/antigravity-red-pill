"""Sellado del turno: un solo punto que asigna el `global_turn` y la identidad.

POR QUÉ EXISTE
--------------
El turno tiene que quedar numerado en tres sitios (reloj, cola de memoria, espejo)
y cada subsistema escribía por su lado. Resultado medido (2026-10-30): 20.204 filas
en `session_mirror`, **cero** con `global_turn > 0`; `fetch_divergent_turns` (D15)
no podía leer nada porque no había nada escrito.

DOS IDENTIFICADORES, DOS TRABAJOS
---------------------------------
- **`global_turn`**: número del reloj. Local, monótono y comparable — `Δ = actual −
  last_seen` sólo significa "turnos paralelos" si es un contador. **No** es un id
  universal: si algún día hay federación, la clave pasa a `(instalación, turno)`.
- **`turn_id`**: identidad del turno. **Nuestro**, no del arnés: 48 bits de tiempo
  en ms + 80 bits aleatorios (base32, 26 caracteres). Ordenable como un timestamp
  y sin ciclo — un contador reiniciaría, un UUIDv4 perdería el orden. El id que
  trae el arnés se guarda como **procedencia** (`request_id`), que es lo que es.
  La vía inversa es un `SELECT ... WHERE request_id = ?`, sin tabla NAT.

CONCURRENCIA
------------
El reloj avanza dentro de `BEGIN IMMEDIATE` y se **relee** después del insert:
SQLite no tiene secuencias y en WAL dos escritores podrían hacer commit en orden
distinto al de inserción, lo que haría que el contador "volviera atrás" para quien
lo lea. `BEGIN IMMEDIATE` toma el lock de escritura antes de leer, así que el
número no se reparte dos veces ni retrocede.

POLÍTICA D2-a
-------------
Sólo un turno conversacional (prompt y respuesta) o con afinidad avanza el reloj.
Señales de dolor, heartbeats o jobs sin afinidad **no** lo tocan: si lo hicieran,
`Δ` dejaría de significar "turnos paralelos" (RFC §3.1, D2-a).
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any, Optional

from red_pill.core.paths import get_session_db

# Bits del identificador: 48 de tiempo (ms, dura ~8.900 años) + 80 aleatorios.
# Con 80 bits, la probabilidad de colisión es despreciable sin coordinador.
_TIME_BITS = 48
_RANDOM_BYTES = 10  # 80 bits
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # sin I, L, O, U (base32 ordenable)


def new_turn_id(now_ms: Optional[int] = None) -> str:
	"""Identificador de turno ordenable por tiempo y sin ciclo (estilo ULID)."""
	ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
	if ms < 0 or ms >= (1 << _TIME_BITS):
		raise ValueError(f"tiempo fuera del rango de {_TIME_BITS} bits: {ms}")
	value = (ms << (_RANDOM_BYTES * 8)) | int.from_bytes(secrets.token_bytes(_RANDOM_BYTES), "big")
	chars = []
	for _ in range(26):
		chars.append(_CROCKFORD[value & 0x1F])
		value >>= 5
	return "".join(reversed(chars))


def is_valid_turn_id(value: str) -> bool:
	"""`True` si tiene la forma de un id nuestro (26 caracteres del alfabeto)."""
	text = str(value or "").strip().upper()
	return len(text) == 26 and all(c in _CROCKFORD for c in text)


def advances_clock(*, role: str, prompt: Optional[str], response: Optional[str], affinity: Any) -> bool:
	"""D2-a: ¿este turno avanza el reloj?

	Conversacional = hay prompt y respuesta (un turno real de ida y vuelta). Una
	señal de dolor o un heartbeat no lo es, aunque llegue con misión.
	"""
	if role not in ("user", "assistant"):
		return False
	has_prompt = bool((prompt or "").strip())
	has_response = bool((response or "").strip())
	if has_prompt and has_response:
		return True
	# Turno de trabajo con afinidad explícita (p.ej. awakening con `mission:…`).
	return bool(affinity)


def next_global_turn(originator: str, affinity: Any = None, *, db_path: Optional[str] = None) -> int:
	"""Avanza el reloj y devuelve el número. Atómico y sin retroceso."""
	import json

	from red_pill.core.affinity import canonize_affinity
	from red_pill.session.store import SessionRegistry

	registry = SessionRegistry(str(db_path) if db_path else str(get_session_db()))
	affinity_json = json.dumps(canonize_affinity(affinity or []), ensure_ascii=False)
	with registry._connect() as conn:  # noqa: SLF001 — el registro es el dueño del esquema
		conn.execute("BEGIN IMMEDIATE")
		cur = conn.execute(
			"INSERT INTO global_turn_seq (created_at, originator, affinity_json) VALUES (?, ?, ?)",
			(time.time(), str(originator or ""), affinity_json),
		)
		turn = int(cur.lastrowid or 0)
		row = conn.execute("SELECT MAX(global_turn) AS m FROM global_turn_seq").fetchone()
		conn.commit()
	# Si otro escritor entró antes que nosotros y su número es mayor, el reloj manda:
	# devolvemos el máximo visto, nunca uno menor que el ya publicado.
	return max(turn, int((row or {})["m"] or 0))


def seal_turn(
	*,
	originator: str,
	requested_id: str = "",
	role: str = "user",
	prompt: Optional[str] = None,
	response: Optional[str] = None,
	affinity: Any = None,
	db_path: Optional[str] = None,
) -> dict:
	"""Sella un turno: identidad propia + número del reloj (si la política lo pide).

	Devuelve `{"turn_id", "global_turn", "requested_id", "advanced"}`. `requested_id`
	se conserva **sólo como procedencia**: si viene repetido de un arnés, no se usa
	como identidad y no puede tragarse un turno.
	"""
	advanced = advances_clock(role=role, prompt=prompt, response=response, affinity=affinity)
	turn = next_global_turn(originator, affinity, db_path=db_path) if advanced else 0
	return {
		"turn_id": new_turn_id(),
		"global_turn": turn,
		"requested_id": str(requested_id or ""),
		"advanced": advanced,
		"pid": os.getpid(),  # únicamente para diagnóstico en logs
	}
