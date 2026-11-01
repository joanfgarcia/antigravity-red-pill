"""Actas del teatro — notas generales, suspensiones y excepciones (AD-095 §teatro).

Qué resuelve
------------
El tablón de misión (`mission_events`) dice **qué pasó en una misión**. No hay sitio
para lo que vale para **todas** las almas: "el pulso de despertar está suspendido a
propósito", "aceptamos el mypy de `cli_services`", "esta decisión se tomó el 29".
Sin ese sitio, cada agente vuelve a preguntar lo mismo al Operador — y el Sentinel
vuelve a gritar por algo ya decidido.

Por qué una tabla y no una pseudo-misión
----------------------------------------
`teatro:general` como `mission_id` sería más barato, pero ensucia el vocabulario
(`mission_id` es NOT NULL y todo el esquema es mission-centric: tablón, digest,
`session_board`, `repo:rama`), obliga a una excepción en el anti-spoof de `post` y
mezcla dos regímenes de visibilidad (misión = pull por afinidad; teatro = todas).
Es un objeto distinto, no un tablón paralelo: **el acta del teatro, no otro registro
de misiones**. Vive en `session.db` (no hay DB nueva) y nadie más la escribe.

Las tres formas, y son una sola
-------------------------------
`type` + `subject` + `expires_at` cubren lo que el Operador pidió:

| Quiero | type | expires_at | Quién lo obedece |
|---|---|---|---|
| Solo dejar constancia | `notice` / `decision` | — | nadie: lo lees |
| Suspender una tarea | `suspension` | opcional (TTL) | **la tarea**, antes de gastar |
| Aceptar un defecto | `waiver` | opcional (TTL) | el emisor de la señal (futuro) |

**Suspender no es apagar.** El proceso sigue vivo (el timer late, el watchdog está
contento); lo que no ocurre es el trabajo caro. Eso mantiene verdadero el invariante
"lo que está encendido, está sano" — apagar un timer para callar al vigilante es
mentirle, no arreglarlo.

Una suspensión que caduca y nadie renueva es una decisión que se deshace sola; por
eso el TTL es lo recomendado y lo permanente se reserva a lo estructural.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from red_pill.session.store import connect_session_db, sanitize_inline

NOTE_TYPES = frozenset({"notice", "decision", "suspension", "waiver"})
# Sujetos que se pueden suspender. `task:` lo lee la tarea; `signal:` lo leerá el
# emisor de la señal (waiver, segunda ola). Texto libre con prefijo conocido.
SUBJECT_PREFIXES = ("task:", "signal:")
_SUMMARY_MAX = 800

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS theatre_notes (
	note_id TEXT PRIMARY KEY,
	type TEXT NOT NULL,
	subject TEXT,
	summary TEXT NOT NULL,
	ref TEXT,
	continuity_id TEXT,
	originator TEXT,
	mission_id TEXT,
	created_at REAL NOT NULL,
	expires_at REAL,
	revoked_at REAL,
	revoked_reason TEXT
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_theatre_subject ON theatre_notes(type, subject)"


def _connect(db_path: Optional[str]):
	from red_pill.core.paths import get_session_db

	return connect_session_db(str(db_path) if db_path else str(get_session_db()))


def ensure_schema(db_path: Optional[str] = None) -> None:
	"""Crea la tabla si falta. Idempotente y non-fatal (mismo patrón que delivery)."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(_INDEX_DDL)
			conn.commit()
	except Exception:
		pass


def post_note(
	*,
	type: str,
	summary: str,
	subject: Optional[str] = None,
	ref: Optional[str] = None,
	continuity_id: Optional[str] = None,
	originator: Optional[str] = None,
	mission_id: Optional[str] = None,
	expires_at: Optional[float] = None,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> Dict[str, Any]:
	"""Escribe un acta. `ValueError` si el tipo o el sujeto no valen.

	`type=suspension|waiver` exige `subject` (`task:…` / `signal:…`): una excepción
	sin sujeto no la puede obedecer nadie, y sería peor que no escribirla.
	"""
	kind = str(type or "").strip().lower()
	if kind not in NOTE_TYPES:
		raise ValueError(f"tipo de acta desconocido: {type!r}")
	subject_clean = str(subject or "").strip() or None
	if subject_clean and not subject_clean.startswith(SUBJECT_PREFIXES):
		raise ValueError(f"el sujeto debe empezar por {SUBJECT_PREFIXES}: {subject!r}")
	if kind in {"suspension", "waiver"} and not subject_clean:
		raise ValueError(f"`{kind}` necesita `subject` ({'task:' if kind == 'suspension' else 'signal:'}…)")
	text = sanitize_inline(summary, _SUMMARY_MAX)
	if not text:
		raise ValueError("summary requerido")
	stamp = float(now) if now is not None else time.time()
	note_id = uuid.uuid4().hex
	with _connect(db_path) as conn:
		conn.execute(_TABLE_DDL)
		conn.execute(_INDEX_DDL)
		conn.execute(
			"INSERT INTO theatre_notes (note_id, type, subject, summary, ref, continuity_id, originator, mission_id, created_at, expires_at)"
			" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
			(
				note_id,
				kind,
				subject_clean,
				text,
				sanitize_inline(ref, 200) if ref else None,
				continuity_id,
				originator,
				mission_id,
				stamp,
				float(expires_at) if expires_at else None,
			),
		)
		conn.commit()
	return {
		"note_id": note_id,
		"type": kind,
		"subject": subject_clean,
		"summary": text,
		"expires_at": float(expires_at) if expires_at else None,
		"created_at": stamp,
	}


def _is_active(note: Dict[str, Any], now: float) -> bool:
	if note.get("revoked_at"):
		return False
	expires = note.get("expires_at")
	return not (expires and float(expires) <= now)


def list_notes(
	*,
	type: Optional[str] = None,
	subject: Optional[str] = None,
	active_only: bool = True,
	limit: int = 50,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> List[Dict[str, Any]]:
	"""Actas, más recientes primero. `active_only` filtra caducadas y revocadas."""
	kind = str(type or "").strip().lower() or None
	if kind and kind not in NOTE_TYPES:
		raise ValueError(f"tipo de acta desconocido: {type!r}")
	params: List[Any] = []
	sql = "SELECT * FROM theatre_notes WHERE 1=1"
	if kind:
		sql += " AND type = ?"
		params.append(kind)
	if subject:
		sql += " AND subject = ?"
		params.append(str(subject).strip())
	sql += " ORDER BY created_at DESC LIMIT ?"
	params.append(max(1, min(int(limit or 50), 200)))
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
	except Exception:
		return []
	stamp = float(now) if now is not None else time.time()
	if active_only:
		rows = [r for r in rows if _is_active(r, stamp)]
	return rows


def suspended(subject: str, *, db_path: Optional[str] = None, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
	"""La suspensión vigente de `subject`, o None.

	Es la pregunta que hace una tarea antes de gastar: *¿me han dicho que no corra?*
	Devuelve la nota entera (no un bool) para poder decir **quién** y **hasta cuándo**.
	"""
	key = str(subject or "").strip()
	if not key:
		return None
	notes = list_notes(type="suspension", subject=key, active_only=True, limit=5, db_path=db_path, now=now)
	return notes[0] if notes else None


def revoke(note_id: str, *, reason: str = "", db_path: Optional[str] = None, now: Optional[float] = None) -> bool:
	"""Levanta un acta (no se borra: se marca revocada y por qué)."""
	nid = str(note_id or "").strip()
	if not nid:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			cur = conn.execute(
				"UPDATE theatre_notes SET revoked_at = ?, revoked_reason = ? WHERE note_id = ? AND revoked_at IS NULL",
				(stamp, sanitize_inline(reason, 200), nid),
			)
			conn.commit()
			return bool(cur.rowcount)
	except Exception:
		return False


def counts(db_path: Optional[str] = None, now: Optional[float] = None) -> Dict[str, int]:
	"""Cuántas actas vigentes hay (para el digest). Nunca lanza."""
	out: Dict[str, int] = {}
	for note in list_notes(active_only=True, limit=200, db_path=db_path, now=now):
		out[str(note.get("type"))] = out.get(str(note.get("type")), 0) + 1
	out["total"] = sum(v for k, v in out.items() if k != "total")
	return out
