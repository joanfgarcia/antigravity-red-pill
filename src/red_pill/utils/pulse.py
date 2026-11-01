import json
import os
import time
from typing import Any, Dict

import red_pill.config as cfg
from red_pill.core.paths import get_state_dir

HEARTBEAT_FILE = str(get_state_dir() / "pulse.json")


def record_interaction() -> Dict[str, Any]:
	"""Records current interaction time and returns cadence stats."""
	now = time.time()
	# `session_start`: desde cuándo va esta sesión. Se reinicia cuando el hueco
	# con el turno anterior es de AUSENCIA (no de una pausa dentro de la charla).
	data = {"last_interaction": now, "prev_interaction": 0.0, "session_start": now}

	if os.path.exists(HEARTBEAT_FILE):
		try:
			with open(HEARTBEAT_FILE, "r") as f:
				old_data = json.load(f)
				data["prev_interaction"] = old_data.get("last_interaction", 0.0)
				prev_start = old_data.get("session_start") or old_data.get("last_interaction") or now
				gap = now - data["prev_interaction"] if data["prev_interaction"] else None
				nueva = gap is None or gap > cfg.CADENCE_ABSENCE_THRESHOLD
				data["session_start"] = now if nueva else prev_start
		except Exception:
			pass

	# CQ-004: Atomic write — write to .tmp, then os.replace() (POSIX-atomic rename).
	# Prevents torn reads in concurrent session scenarios: readers always see
	# either the complete old file or the complete new file, never a partial write.
	_atomic_write_heartbeat(data)

	delta = now - data["prev_interaction"] if data["prev_interaction"] > 0 else 0

	status = "normal"
	if data["prev_interaction"] == 0:
		status = "initial"
	elif delta < cfg.CADENCE_BURST_THRESHOLD:
		status = "burst"
	elif delta > cfg.CADENCE_ABSENCE_THRESHOLD:
		status = "dormant"

	return {"status": status, "delta_seconds": delta, "delta_human": _human_time(delta)}


_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _stamp(ts: float) -> str:
	"""Fecha local con offset y día de la semana: `2026-10-31 14:52 (sáb)`."""
	from datetime import datetime

	d = datetime.fromtimestamp(ts).astimezone()
	return f"{d.strftime('%Y-%m-%d %H:%M')} ({_DIAS[d.weekday()]})"


def time_line(now: float | None = None) -> str:
	"""Línea de tiempo para el handshake: qué hora es, cuánto hace del turno
	anterior y desde cuándo va la sesión.

	Pedido del Operador (2026-10-31): sin esto no puedo distinguir "ayer" de "hace
	dos turnos", y una memoria que confunde esas dos escalas miente sobre el
	tiempo. Se lee de `pulse.json` (lo escribe `record_interaction` en el pase de
	memoria); no escribe nada y nunca lanza.
	"""
	now = time.time() if now is None else now
	session_start = None
	prev = 0.0
	try:
		if os.path.exists(HEARTBEAT_FILE):
			with open(HEARTBEAT_FILE, "r") as f:
				data = json.load(f)
			prev = float(data.get("last_interaction") or 0.0)
			session_start = float(data.get("session_start") or 0.0) or None
	except Exception:
		pass

	partes = [f"- Ahora: {_stamp(now)}"]
	if prev > 0:
		delta = now - prev
		partes.append(f"turno anterior: hace {_human_time(delta)}")
	if session_start:
		partes.append(f"sesión desde {_stamp(session_start)} ({_human_time(now - session_start)})")
	return " · ".join(partes)


def _atomic_write_heartbeat(data: Dict[str, Any]) -> None:
	"""
	Writes heartbeat data atomically to HEARTBEAT_FILE.

	Pattern: write to <HEARTBEAT_FILE>.tmp → os.replace() → HEARTBEAT_FILE.
	os.replace() is guaranteed atomic on POSIX (same filesystem).
	"""
	heartbeat_dir = os.path.dirname(HEARTBEAT_FILE)
	os.makedirs(heartbeat_dir, exist_ok=True)

	tmp_path = HEARTBEAT_FILE + ".tmp"
	try:
		with open(tmp_path, "w") as f:
			json.dump(data, f)
			f.flush()
			os.fsync(f.fileno())  # Flush kernel buffers to disk before rename
		os.replace(tmp_path, HEARTBEAT_FILE)
	except Exception:
		# Best-effort cleanup of temp file on failure
		try:
			os.unlink(tmp_path)
		except OSError:
			pass
		raise


def _human_time(seconds: float) -> str:
	if seconds < 60:
		return f"{int(seconds)}s"
	if seconds < 3600:
		return f"{int(seconds // 60)}m"
	if seconds < 86400:
		return f"{int(seconds // 3600)}h"
	return f"{int(seconds // 86400)}d"
