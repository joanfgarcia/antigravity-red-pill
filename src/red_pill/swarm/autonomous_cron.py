#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path

import platformdirs
from dotenv import load_dotenv


def is_ide_idle(idle_seconds=3600):
	"""
	Heurística de inactividad: Comprueba cuándo fue la última vez que el usuario
	interactuó con el IDE leyendo la fecha de modificación de los logs de conversación.
	"""
	brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
	if not os.path.exists(brain_dir):
		return True

	latest_time = 0.0
	for root, _, files in os.walk(brain_dir):
		for f in files:
			if f == "overview.txt":
				try:
					mtime = os.path.getmtime(os.path.join(root, f))
					if mtime > latest_time:
						latest_time = mtime
				except Exception:
					pass
	return (time.time() - latest_time) > idle_seconds


def main():
	# Cargar configuración soberana de Red-Pill (Identidad)
	red_pill_config = Path(platformdirs.user_config_dir("red-pill")) / ".env"
	if red_pill_config.exists():
		load_dotenv(red_pill_config)

	# Cargar configuración de Neon-Link (Base de datos)
	neon_link_config = Path(platformdirs.user_config_dir("neon-link")) / ".env"
	if neon_link_config.exists():
		load_dotenv(neon_link_config)

	db_path = os.environ.get("NEON_LINK_DB_PATH", Path(platformdirs.user_data_dir("neon-link")) / "events.db")
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

	# Obtener el último canal activo de forma dinámica y agnóstica
	cursor.execute("SELECT channel_user_id, channel FROM inbox ORDER BY created_at DESC LIMIT 1")
	row = cursor.fetchone()
	if not row:
		print("No hay historial de canales activos. Abortando.")
		return
	channel_user_id, channel = row

	msg = {
		"text": f"SYSTEM: [AUTONOMOUS AWAKENING]. {user_name} está offline. Tienes tiempo libre y autonomía. Puedes reflexionar en voz alta, proponer ideas de arquitectura en el canal activo, o simplemente descansar.",
		"mode": "conversational",
	}

	cursor.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, status) VALUES (?, ?, ?, ?)", (channel, channel_user_id, json.dumps(msg), "PENDING")
	)
	conn.commit()
	conn.close()
	print("Señal de despertar autónomo inyectada en el Córtex (events.db)")


if __name__ == "__main__":
	main()
