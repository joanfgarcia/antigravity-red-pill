"""Bridge del arnés — resolución del CUERPO (session_id) por instancia.

El bridge es lo único que el hook del arnés conoce y el servidor MCP (cwd =
checkout del kernel) no: qué sesión nativa está sirviendo a ESTA instancia.
Hubo un tiempo en que bastaba un fichero global por arnés
(`state/<harness>_session.json`): lo escribe el hook y lo lee el proxy/backend.

Con varias pestañas vivas ese fichero único no identifica: todas las
instancias escriben en él y gana la ÚLTIMA, así que un alma puede acabar
atribuida al cuerpo (session_id) de otra pestaña (D-BRIDGE, 2026-10-28).

La correlación que SÍ distingue: la instancia del proxy tiene un `cwd` propio
(la app de escritorio hospeda varias instancias con cwd distinto), y
`opencode.db` guarda el `directory` de cada sesión. Cruzando cwd-de-instancia
con sesiones **vivas** (`session_liveness`) se resuelve el cuerpo sin depender
de quién escribió después.

Degradación honesta: si hay VARIAS candidatas vivas para el mismo cwd (dos
pestañas en el mismo workspace), la correlación no es inequívoca y se cae al
bridge global (comportamiento anterior); el bug persiste solo en ese caso.

Módulo puro de lectura, non-fatal: cualquier fallo degrada, nunca lanza.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from red_pill.core.paths import get_state_dir

logger = logging.getLogger(__name__)

SESSION_BRIDGE_SUBDIR = "sessions/bridge"
# Frescura mínima del latido para aceptar una sesión como "candidata" en la
# correlación. Un poco más laxo que el `is_active` del tablón: el proxy corre al
# arranque del turno y queremos ver la sesión que acaba de escribir.
_CORRELATION_WINDOW_S = 900.0


def _safe(token: str) -> str:
	"""Sanea un token para el nombre del bridge: DEBE casar con el JS.

	Paridad exacta con `sessionBridgePath` de `seeds/opencode/plugins/redpill-scribe.js`
	(que hace `String(x).replace(/[/:]/g, "_").replace(/__/g, "_")`): si los dos
	lados no producen el mismo nombre, el proxy no encuentra el bridge escrito por
	el hook. Se escapan `/` y `:` (separadores peligrosos) y se colapsa `__` (que
	es el delimitador `provider__session`).
	"""
	return str(token).replace("/", "_").replace(":", "_").replace("__", "_")


def session_bridge_dir() -> Path:
	"""`${STATE_DIR}/sessions/bridge` (lectores: no lo crean)."""
	return get_state_dir() / SESSION_BRIDGE_SUBDIR


def read_session_bridge(provider: str, session_id: str) -> Optional[dict]:
	"""Lee el bridge POR SESIÓN (`opencode__<sid>.json`), o None si no existe."""
	if not provider or not session_id:
		return None
	path = session_bridge_dir() / f"{_safe(provider)}__{_safe(session_id)}.json"
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return None
	return data if isinstance(data, dict) else None


def _opencode_db_path() -> Path:
	from red_pill.core.paths import get_xdg_data_home

	return get_xdg_data_home() / "opencode" / "opencode.db"


def _live_session_ids(provider: str, window_s: float = _CORRELATION_WINDOW_S) -> List[str]:
	"""Sesiones con latido reciente del provider (más reciente primero)."""
	from red_pill.core.session_liveness import list_sessions

	try:
		signals = list_sessions()
	except Exception:
		return []
	return [s.session_id for s in signals if s.provider == provider and s.is_active(active_seconds=int(window_s))]


def _session_directory(session_id: str) -> Optional[str]:
	"""`session.directory` de una sesión opencode (read-only), o None."""
	db = _opencode_db_path()
	if not db.exists():
		return None
	try:
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		try:
			row = con.execute("SELECT directory FROM session WHERE id = ?", (session_id,)).fetchone()
		finally:
			con.close()
	except Exception:
		return None
	return str(row[0]) if row and row[0] else None


def list_session_bridges(provider: str, max_age_s: float = _CORRELATION_WINDOW_S) -> List[dict]:
	"""Bridges per-sesión del provider **frescos**, más reciente primero.

	Es la fuente primaria de la correlación: el hook acaba de escribir el de ESTA
	instancia, y `opencode.db` puede no tener aún la fila de la sesión viva
	(opencode persiste la `session` de forma perezosa — verificado 2026-10-28:
	731 sesiones históricas con `directory`, pero la sesión del turno en curso
	aún no estaba). El bridge per-sesión sí existe en cuanto el turno arranca.

	**Frescura obligatoria:** se descartan los bridges más viejos que `max_age_s`.
	Un bridge rancio es de una pestaña cerrada; devolverlo atribuiría a esta
	instancia el cuerpo de una sesión muerta (bug de la auditoría 2026-10-28).
	Nunca se borran ficheros aquí (solo lectura); el barrido es del janitor.
	"""
	import time as _time

	directory = session_bridge_dir()
	try:
		items = [p for p in directory.iterdir() if p.is_file() and p.name.startswith(f"{_safe(provider)}__") and p.name.endswith(".json")]
	except (FileNotFoundError, NotADirectoryError):
		return []
	now = _time.time()
	entries: List[tuple] = []
	for p in items:
		try:
			entry = json.loads(p.read_text(encoding="utf-8"))
		except Exception:
			continue
		if not isinstance(entry, dict):
			continue
		updated = float(entry.get("updated_at") or 0.0)
		if max_age_s and (updated <= 0.0 or now - updated > max_age_s):
			continue
		entries.append((updated, entry))
	entries.sort(key=lambda t: t[0], reverse=True)
	return [e for _, e in entries]


def _norm(path: str) -> str:
	"""Normaliza una ruta para comparar (expanduser + realpath + normpath).

	`realpath` resuelve symlinks: un workspace abierto por su enlace y por su
	ruta real es el MISMO workspace, y sin resolverlos la correlación degradaba
	en silencio al bridge global (hay que casar por identidad, no por deletreo).
	"""
	if not path:
		return ""
	return os.path.normpath(os.path.realpath(os.path.expanduser(str(path))))


def resolve_body_by_cwd(provider: str, cwd: str) -> Optional[dict]:
	"""Cuerpo de la sesión que sirve a ESTA instancia, por correlación de cwd.

	Estrategia por capas (de la señal más directa a la de degradación). **La
	vitalidad (`session_liveness`) se consulta en TODAS las capas**: un bridge
	per-sesión rancio de una pestaña cerrada en el mismo workspace no puede ganar
	a la sesión viva de esta instancia (bug detectado por la auditoría adversarial
	del 2026-10-28 — la capa 1 lo devolvía sin mirar el latido).

	1. **Bridges per-sesión con `workdir` == cwd, de sesión VIVA.** Señal primaria:
		el hook acaba de escribir el suyo y la sesión late, aunque aún no esté en
		`opencode.db`. Si EXACTAMENTE uno casa → ese cuerpo.
	2. **Correlación por `opencode.db`** (`session.directory` == cwd) entre las
		sesiones **vivas**: confirma/desempata cuando la capa 1 no decide (varios
		bridges en el mismo cwd, o el propio aún sin escribir).
	3. **Carrera:** varios bridges en el mismo cwd pero solo UNA sesión viva entre
		ellos (los demás son pestañas cerradas con bridge rancio) → la viva.
	4. Si nada casa de forma inequívoca → None (el proxy degrada al bridge global,
		comportamiento anterior; el bug persiste solo ahí).
	"""
	if not provider or not cwd:
		return None
	target = _norm(cwd)
	if not target:
		return None

	live = _live_session_ids(provider)
	live_set = set(live)

	# Capa 1: bridges per-sesión cuyo workdir == cwd Y cuya sesión está viva.
	by_cwd = [
		e for e in list_session_bridges(provider) if e.get("session_id") and _norm(str(e.get("workdir") or "")) == target
	]
	by_cwd_live = [e for e in by_cwd if e.get("session_id") in live_set]
	if len(by_cwd_live) == 1:
		return by_cwd_live[0]

	# Capa 2: correlación por opencode.db entre las vivas (desempate).
	db_matches = [sid for sid in live if _norm(str(_session_directory(sid) or "")) == target]
	if len(db_matches) == 1:
		entry = read_session_bridge(provider, db_matches[0])
		if entry:
			return entry
		return {"provider": provider, "session_id": db_matches[0], "workdir": cwd}

	return None
