#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from red_pill.core.origins import PROVIDER_PI, read_origins
from red_pill.core.paths import (
	get_antigravity_brain_dir,
	get_awakening_log_path,
	get_config_dir,
	get_neon_link_config_dir,
	get_neon_link_db_path,
	get_state_dir,
)
from red_pill.swarm.bridges.opencode import read_opencode_origins

# Actividad EN DISCO de los IDEs sin interceptor propio (29 jul 2026): el touch
# de last_user_activity.txt depende de que el agente llame al handshake — una
# sesión amnésica o un run headless no lo hace, y el despertar interrumpía al
# operador en plena faena. Los ficheros de sesión no mienten: se escriben en
# cada turno, llame el agente al handshake o no. (Mismas rutas canónicas que
# chronicle_sources/{claude_code,opencode}.py.)
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
OPENCODE_DATA_DIR = Path.home() / ".local" / "share" / "opencode"
PI_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"

# `<timestamp>_<uuid>.jsonl` → el `session_id` que registra el bridge de Pi.
_PI_SESSION_ID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.IGNORECASE)

# Registro del último despertar (lo escribe `agent_worker` al abrir/cerrar el run).
AWAKENING_STATE_FILE = "last_awakening.json"

# Tolerancia entre el touch del handshake y el cierre registrado del despertar:
# el bridge escribe el estado al terminar, pero el último turno pudo tocar el
# fichero unos segundos antes (o después, si el cierre tarda).
_AWAKENING_TOUCH_GRACE = 120.0


def _pi_session_id(path: Path) -> str:
	match = _PI_SESSION_ID.search(path.name)
	return match.group(1) if match else path.stem


def _newest_age(paths):
	"""Antigüedad (s) del fichero más reciente de `paths`, o None si no hay."""
	newest = None
	for path in paths:
		try:
			age = time.time() - path.stat().st_mtime
		except Exception:
			continue
		if newest is None or age < newest:
			newest = age
	return newest


def _read_last_awakening(now, idle_seconds):
	"""Registro del último despertar si su cierre cae dentro del periodo vigilado.

	Lo escribe `agent_worker` en `state/last_awakening.json` al abrir y cerrar
	cada run (`running` → `worked` / `silence` / `error`). Sin este registro el
	gate no puede distinguir el touch del handshake del propio despertar de una
	presencia real del Operador.
	"""
	path = get_state_dir() / AWAKENING_STATE_FILE
	try:
		data = json.loads(path.read_text())
	except Exception:
		return None
	if not isinstance(data, dict):
		return None
	ended = data.get("ended_at", data.get("started_at"))
	if not isinstance(ended, (int, float)) or (now - ended) > idle_seconds:
		return None
	return data


def _attribute_touch(record, mtime):
	"""A quién pertenece la frescura de `last_user_activity.txt`.

	Devuelve `(clase, detalle)`: `operator`, `awakening_worked` o
	`awakening_silence`. Un despertar que **trabajó** cuenta como actividad (se
	respeta el intervalo de una hora, pero el log lo dice: no es el Operador);
	uno que ejerció el **Derecho al Silencio** no cuenta — su turno tocó el
	fichero solo por el handshake y no debe bloquear el siguiente despertar.
	"""
	if not record:
		return "operator", "sin registro de despertar reciente"
	started = record.get("started_at")
	ended = record.get("ended_at", started)
	if not isinstance(started, (int, float)) or not isinstance(ended, (int, float)):
		return "operator", "registro de despertar incompleto"
	if mtime < started - _AWAKENING_TOUCH_GRACE or mtime > ended + _AWAKENING_TOUCH_GRACE:
		return "operator", "touch posterior al cierre del despertar"
	status = record.get("status")
	if status == "silence":
		return "awakening_silence", "Derecho al Silencio: no cuenta como actividad"
	if status in ("worked", "running", "error"):
		return "awakening_worked", f"despertar {status}"
	return "operator", f"estado de despertar desconocido: {status!r}"


def activity_state(idle_seconds=3600):
	"""
	Estado de presencia del Operador con su causa (bool `is_ide_idle` delega aquí).

	Señales (OR — cualquiera activa = operador presente):
	1. last_user_activity.txt (handshake de CUALQUIER IDE / Telegram worker),
	atribuido al Operador o al último despertar según su registro
	2. Antigravity IDE transcript.jsonl files (direct IDE sessions)
	3. Claude Code: transcripts JSONL de ~/.claude/projects (escritos en vivo)
	4. opencode: su base local (db/WAL mutan en cada turno)
	5. Pi: transcripts JSONL de ~/.pi/agent/sessions (escritos en vivo; los runs
	headless de awakening se excluyen por el registro de orígenes)

	`idle` es True solo si TODAS las señales indican inactividad > `idle_seconds`.
	"""
	now = time.time()

	def _active(reason, detail, age):
		return {"idle": False, "reason": reason, "detail": detail, "age_s": age}

	# Signal 1: handshake de cualquier IDE / Telegram worker touch file. El
	# despertar también lo toca (sus turnos llaman al handshake), así que la
	# frescura se atribuye con el registro del último despertar.
	state_file = get_state_dir() / "last_user_activity.txt"
	try:
		age = now - state_file.stat().st_mtime
	except OSError:
		age = None
	if age is not None and age <= idle_seconds:
		reason, detail = _attribute_touch(_read_last_awakening(now, idle_seconds), state_file.stat().st_mtime)
		if reason != "awakening_silence":
			return _active(reason, f"{detail} · last_user_activity.txt", age)

	# Signal 2: Antigravity IDE active conversations
	# Transcripts are written in real-time during IDE sessions.
	antigravity_brain = get_antigravity_brain_dir()
	if antigravity_brain.is_dir():
		try:
			age = _newest_age(antigravity_brain.rglob("transcript.jsonl"))
			if age is not None and age <= idle_seconds:
				return _active("operator", "Antigravity: transcript.jsonl", age)
		except Exception:
			pass

	# Signal 3: Claude Code sessions (interactivas, chips y headless)
	if CLAUDE_PROJECTS_DIR.is_dir():
		try:
			age = _newest_age(CLAUDE_PROJECTS_DIR.rglob("*.jsonl"))
			if age is not None and age <= idle_seconds:
				return _active("operator", "Claude Code: transcript .jsonl", age)
		except Exception:
			pass

	# Signal 4: opencode local storage. Distinguish real operator sessions from
	# autonomous-awakening headless runs via the origin registry: a fresh session
	# only counts as activity if it is NOT an "awakening" run. A session with no
	# registry entry is assumed to be user activity (safe default). If the DB can't
	# be read, fall back to the raw opencode.db mtime check.
	if OPENCODE_DATA_DIR.is_dir():
		try:
			origins = read_opencode_origins()
			db = OPENCODE_DATA_DIR / "opencode.db"
			if db.exists():
				cutoff_ms = int((now - idle_seconds) * 1000)
				con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
				try:
					fresh = con.execute("SELECT id, time_updated FROM session WHERE time_updated > ?", (cutoff_ms,)).fetchall()
				finally:
					con.close()
				ages = [now - ts / 1000 for sid, ts in fresh if origins.get(sid, {}).get("origin", "user") != "awakening"]
				if ages:
					return _active("operator", "opencode: sesión activa", min(ages))
			else:
				age = _newest_age(OPENCODE_DATA_DIR.glob("opencode.db*"))
				if age is not None and age <= idle_seconds:
					return _active("operator", "opencode.db reciente", age)
		except Exception:
			age = _newest_age(OPENCODE_DATA_DIR.glob("opencode.db*"))
			if age is not None and age <= idle_seconds:
				return _active("operator", "opencode.db reciente", age)

	# Signal 5: Pi sessions (`~/.pi/agent/sessions`). Its extension does not touch
	# the activity file per turn, so the JSONL transcript is the only live signal.
	# Headless awakening runs write there too: exclude them via the origin registry
	# (same policy as opencode). A session with no registry entry is user activity.
	if PI_SESSIONS_DIR.is_dir():
		try:
			pi_origins = read_origins(PROVIDER_PI)
			ages = []
			for path in PI_SESSIONS_DIR.rglob("*.jsonl"):
				try:
					age = now - path.stat().st_mtime
				except OSError:
					continue
				if age > idle_seconds:
					continue
				if (pi_origins.get(_pi_session_id(path)) or {}).get("origin") != "awakening":
					ages.append(age)
			if ages:
				return _active("operator", "Pi: sesión activa", min(ages))
		except Exception:
			pass

	# All signals indicate idle
	return {"idle": True, "reason": "idle", "detail": "", "age_s": None}


def is_ide_idle(idle_seconds=3600):
	"""True solo si TODAS las señales indican inactividad > `idle_seconds`."""
	return activity_state(idle_seconds)["idle"]


def describe_activity(state):
	"""Mensaje honesto del aborto: distingue al Operador del propio despertar."""
	if state.get("reason") == "awakening_worked":
		age = state.get("age_s")
		mins = int(age // 60) if isinstance(age, (int, float)) else 0
		return (
			f"El último despertar trabajó hace {mins} min ({state.get('detail')}). "
			"Se respeta el intervalo de una hora, aunque no haya Operador delante."
		)
	return "El Operador sigue activo en el IDE. Abortando despertar autónomo para no interrumpir."


def _log(msg: str) -> None:
	print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def main():
	# Cargar configuración soberana de Red-Pill (Identidad)
	red_pill_config = get_config_dir() / ".env"
	if red_pill_config.exists():
		load_dotenv(red_pill_config)

	# Cargar configuración de Neon-Link (Base de datos)
	neon_link_config = get_neon_link_config_dir() / ".env"
	if neon_link_config.exists():
		load_dotenv(neon_link_config)

	db_path = os.environ.get("NEON_LINK_DB_PATH", get_neon_link_db_path())
	user_name = os.environ.get("USER_NAME", "Operador")

	# Comprobar si el Operador lleva inactivo 1 hora (3600 segundos) — y de quién
	# es la actividad: el propio despertar también toca el fichero del handshake.
	state = activity_state(3600)
	if not state["idle"]:
		_log(describe_activity(state))
		return

	conn = sqlite3.connect(db_path)
	cursor = conn.cursor()

	# Evitar inyectar un despertar si ya hay mensajes pendientes en la cola
	cursor.execute("SELECT count(*) FROM inbox WHERE status = 'PENDING'")
	if cursor.fetchone()[0] > 0:
		_log("La cola de Neon-Link no está vacía. Abortando despertar.")
		return

	# AWAKENINGs always go through the 'system' channel to avoid
	# polluting user Telegram sessions with autonomous wake-ups
	channel = "system"
	channel_user_id = "autonomous_awakening"

	log_path = get_awakening_log_path()
	planner_access = os.environ.get("AWAKENING_PLANNER_ACCESS", "planner")
	planner_hint = (
		" Puedes mirar el planner del desk (ideas/pending) y decidir si contribuir a algo — política AWAKENING_PLANNER_ACCESS en tu prompt."
		if planner_access not in ("none", "")
		else " No contribuyas al planner del desk (política: none)."
	)
	msg = {
		"text": (
			f"SYSTEM: [AUTONOMOUS AWAKENING]. {user_name} está offline. Tienes autonomía absoluta.\n\n"
			f"DIRECTIVA:\n"
			f"1. Registra este despertar en `{log_path}` (fecha, hora y qué vas a hacer).\n"
			f"2. Si decides ejercer tu Derecho al Silencio, escribe el log allí y responde por aquí "
			f"ÚNICAMENTE con: 'Ejercicio consciente del Derecho al Silencio. Estado del Búnker: calma.' "
			f"(no irá a Telegram).\n"
			f"3. Si decides trabajar, reflexiona o escribe código, y luego manda un mensaje por aquí "
			f"resumiéndolo para Telegram.{planner_hint}"
		),
		"mode": "conversational",
	}

	cursor.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, status) VALUES (?, ?, ?, ?)", (channel, channel_user_id, json.dumps(msg), "PENDING")
	)
	conn.commit()
	conn.close()
	_log("Señal de despertar autónomo inyectada en el Córtex (events.db) via canal 'system'")


if __name__ == "__main__":
	main()
