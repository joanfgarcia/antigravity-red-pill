#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from red_pill.core.paths import (
	get_aleth_core_root,
	get_antigravity_brain_dir,
	get_config_dir,
	get_neon_link_config_dir,
	get_neon_link_db_path,
	get_state_dir,
)

# Actividad EN DISCO de los IDEs sin interceptor propio (29 jul 2026): el touch
# de last_user_activity.txt depende de que el agente llame al handshake — una
# sesión amnésica o un run headless no lo hace, y el despertar interrumpía al
# operador en plena faena. Los ficheros de sesión no mienten: se escriben en
# cada turno, llame el agente al handshake o no. (Mismas rutas canónicas que
# chronicle_sources/{claude_code,opencode}.py.)
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
OPENCODE_DATA_DIR = Path.home() / ".local" / "share" / "opencode"


def is_ide_idle(idle_seconds=3600):
	"""
	Heurística de inactividad multi-señal.

	Señales (OR — cualquiera activa = operador presente):
	1. last_user_activity.txt (handshake de CUALQUIER IDE / Telegram worker)
	2. Antigravity IDE transcript.jsonl files (direct IDE sessions)
	3. Claude Code: transcripts JSONL de ~/.claude/projects (escritos en vivo)
	4. opencode: su base local (db/WAL mutan en cada turno)

	Returns True ONLY if ALL signals indicate idle > idle_seconds.
	"""
	now = time.time()

	def _any_fresh(paths):
		for path in paths:
			try:
				if (now - path.stat().st_mtime) <= idle_seconds:
					return True
			except Exception:
				continue
		return False

	# Signal 1: handshake de cualquier IDE / Telegram worker touch file
	state_file = get_state_dir() / "last_user_activity.txt"
	if state_file.exists() and _any_fresh([state_file]):
		return False

	# Signal 2: Antigravity IDE active conversations
	# Transcripts are written in real-time during IDE sessions.
	antigravity_brain = get_antigravity_brain_dir()
	if antigravity_brain.is_dir():
		try:
			if _any_fresh(antigravity_brain.rglob("transcript.jsonl")):
				return False
		except Exception:
			pass

	# Signal 3: Claude Code sessions (interactivas, chips y headless)
	if CLAUDE_PROJECTS_DIR.is_dir():
		try:
			if _any_fresh(CLAUDE_PROJECTS_DIR.rglob("*.jsonl")):
				return False
		except Exception:
			pass

	# Signal 4: opencode local storage
	try:
		if OPENCODE_DATA_DIR.is_dir() and _any_fresh(OPENCODE_DATA_DIR.glob("opencode.db*")):
			return False
	except Exception:
		pass

	# All signals indicate idle
	return True


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

	# Comprobar si el Operador lleva inactivo 1 hora (3600 segundos)
	if not is_ide_idle(3600):
		print("El Operador sigue activo en el IDE. Abortando despertar autónomo para no interrumpir.")
		return

	conn = sqlite3.connect(db_path)
	cursor = conn.cursor()

	# Evitar inyectar un despertar si ya hay mensajes pendientes en la cola
	cursor.execute("SELECT count(*) FROM inbox WHERE status = 'PENDING'")
	if cursor.fetchone()[0] > 0:
		print("La cola de Neon-Link no está vacía. Abortando despertar.")
		return

	# AWAKENINGs always go through the 'system' channel to avoid
	# polluting user Telegram sessions with autonomous wake-ups
	channel = "system"
	channel_user_id = "autonomous_awakening"

	log_path = get_aleth_core_root() / "AWAKENING_LOG.md"
	msg = {
		"text": f"SYSTEM: [AUTONOMOUS AWAKENING]. {user_name} está offline. Tienes autonomía absoluta.\n\nDIRECTIVA:\n1. Registra este despertar en `{log_path}` (fecha, hora y qué vas a hacer).\n2. Si decides ejercer tu Derecho al Silencio, escribe el log allí y responde por aquí ÚNICAMENTE con: 'Ejercicio consciente del Derecho al Silencio. Estado del Búnker: calma.' (no irá a Telegram).\n3. Si decides trabajar, reflexiona o escribe código, y luego manda un mensaje por aquí resumiéndolo para Telegram.",
		"mode": "conversational",
	}

	cursor.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, status) VALUES (?, ?, ?, ?)", (channel, channel_user_id, json.dumps(msg), "PENDING")
	)
	conn.commit()
	conn.close()
	print("Señal de despertar autónomo inyectada en el Córtex (events.db) via canal 'system'")


if __name__ == "__main__":
	main()
