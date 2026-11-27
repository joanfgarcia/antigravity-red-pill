"""Desk (Dokimé) como consumidor residente de GPU — pausa y devolución.

Fase 0 del arbitraje de VRAM (2026-11-27): el desk mantiene un `llama-server`
propio en el contenedor `dokime-llama`, con el modelo cargado aunque nadie lo
use. El daemon no puede compartir esa VRAM (es otro proceso), así que cualquier
etapa que necesite cargar un modelo distinto se queda sin sitio y —desde el
arreglo del éxito silencioso— difiere el ciclo.

Este módulo es el cuchillo pequeño: si el desk está **ocioso** (su log no tiene
actividad reciente), se para; el job apunta que lo paró él y lo devuelve al
terminar (`teardown`, que corre en todas las salidas, deferral incluido). No es
un broker ni un scheduler: no reparte prioridades ni encola peticiones. Eso
solo hace falta si algún día hay varios inquilinos compitiendo a la vez.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Optional

from red_pill.core.paths import get_state_dir

logger = logging.getLogger(__name__)

DEFAULT_CONTAINER = "dokime-llama"
_STATE_NAME = "desk_gpu_paused.json"

# `podman logs --timestamps`: 2026-11-26T20:20:46.532488000+01:00 …
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$")


def container() -> str:
	"""Nombre del contenedor del modelo del desk (override por entorno para tests)."""
	return os.getenv("REDPILL_DESK_LLAMA_CONTAINER", DEFAULT_CONTAINER)


def _podman(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
	"""`podman <args>` con captura. Indirección única: los tests la sustituyen."""
	try:
		return subprocess.run(["podman", *args], capture_output=True, text=True, timeout=timeout)
	except Exception as exc:  # noqa: BLE001 — sin podman esto es «no hay desk»
		return subprocess.CompletedProcess(["podman", *args], 127, "", str(exc))


def exists(name: Optional[str] = None) -> bool:
	name = name or container()
	return _podman(["container", "exists", name]).returncode == 0


def is_running(name: Optional[str] = None) -> bool:
	name = name or container()
	out = _podman(["inspect", "-f", "{{.State.Running}}", name])
	return out.returncode == 0 and (out.stdout or "").strip() == "true"


def _parse_ts(raw: str) -> Optional[float]:
	match = _TS_RE.match(raw.strip())
	if not match:
		return None
	base, frac, tz = match.groups()
	frac = (frac or "0")[:6].ljust(6, "0")
	try:
		dt = datetime.fromisoformat(f"{base}.{frac}{tz or ''}")
	except ValueError:
		return None
	return dt.timestamp()


def last_activity_ts(name: Optional[str] = None) -> Optional[float]:
	"""Timestamp de la última línea del log del servidor (petición o arranque)."""
	name = name or container()
	out = _podman(["logs", "--timestamps", "--tail", "1", name])
	if out.returncode != 0:
		return None
	line = (out.stdout or "").strip().splitlines()
	if not line:
		return None
	# `podman logs` mezcla stderr en algunos casos; buscar la primera marca válida.
	for candidate in (line[0], (out.stderr or "").strip().splitlines()[0] if (out.stderr or "").strip() else ""):
		if not candidate:
			continue
		ts = _parse_ts(candidate.split(" ", 1)[0])
		if ts is not None:
			return ts
	return None


def idle_seconds(name: Optional[str] = None) -> Optional[float]:
	"""Segundos desde la última actividad. `None` = no se puede saber (no ocioso)."""
	ts = last_activity_ts(name)
	if ts is None:
		return None
	return max(0.0, time.time() - ts)


def state_path():
	path = get_state_dir() / _STATE_NAME
	return path


def load_state() -> Optional[Dict[str, Any]]:
	path = state_path()
	if not path.exists():
		return None
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except Exception as exc:  # noqa: BLE001 — un estado roto no debe romper el ciclo
		logger.warning(f"[GPU-DESK] estado ilegible ({path}): {exc}")
		return None


def _save_state(state: Dict[str, Any]) -> None:
	path = state_path()
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
	tmp.replace(path)


def _clear_state() -> None:
	try:
		state_path().unlink(missing_ok=True)
	except Exception as exc:  # noqa: BLE001
		logger.warning(f"[GPU-DESK] no se pudo borrar el estado: {exc}")


def pause_if_idle(min_idle_s: int, job_id: str, name: Optional[str] = None) -> bool:
	"""Para el modelo del desk si lleva `min_idle_s` sin actividad.

	Devuelve True solo si lo paró ESTA llamada (y deja el estado para el
	`teardown`). Nunca toca un desk en uso: sin lectura de actividad fiable, no
	se para (§ la duda se resuelve a favor del Operador).
	"""
	name = name or container()
	if not exists(name) or not is_running(name):
		return False
	state = load_state()
	if state and state.get("job_id") == job_id:
		return False  # ya lo paró este job (idempotente)
	if state:
		# Lo paró otro job que aún no lo ha devuelto: no pisar su estado.
		logger.info(f"[GPU-DESK] '{name}' ya está pausado por el job {state.get('job_id')}; no se toca.")
		return False
	idle = idle_seconds(name)
	if idle is None:
		logger.info(f"[GPU-DESK] '{name}': sin lectura de actividad — no se para (conservador).")
		return False
	if idle < min_idle_s:
		logger.info(f"[GPU-DESK] '{name}' activo hace {idle:.0f}s (< {min_idle_s}s): no se para.")
		return False
	stop = _podman(["stop", name], timeout=90)
	if stop.returncode != 0:
		logger.warning(f"[GPU-DESK] no se pudo parar '{name}': {(stop.stderr or '').strip()[:200]}")
		return False
	_save_state({"container": name, "job_id": job_id, "stopped_at": time.time(), "idle_s": round(idle, 1)})
	logger.info(f"[GPU-DESK] modelo del desk parado (ocio {idle:.0f}s) por el job {job_id}; se devuelve en teardown.")
	return True


def resume(job_id: Optional[str] = None, name: Optional[str] = None) -> bool:
	"""Devuelve el modelo al desk si lo paró `job_id` (o cualquiera si es None)."""
	state = load_state()
	if not state:
		return False
	if job_id is not None and state.get("job_id") != job_id:
		return False
	target = name or str(state.get("container") or container())
	if not exists(target):
		logger.warning(f"[GPU-DESK] estado huérfano: el contenedor '{target}' ya no existe.")
		_clear_state()
		return False
	if is_running(target):
		_clear_state()
		return False
	start = _podman(["start", target], timeout=90)
	if start.returncode != 0:
		logger.warning(f"[GPU-DESK] no se pudo arrancar '{target}': {(start.stderr or '').strip()[:200]}")
		return False
	_clear_state()
	logger.info(f"[GPU-DESK] modelo del desk devuelto ('{target}').")
	return True


def status() -> Dict[str, Any]:
	"""Radiografía para CLI/tests: contenedor, estado, ocio y pausa pendiente."""
	name = container()
	state = load_state()
	idle = idle_seconds(name) if exists(name) and is_running(name) else None
	return {
		"container": name,
		"exists": exists(name),
		"running": is_running(name),
		"idle_s": None if idle is None else round(idle, 1),
		"paused_by": (state or {}).get("job_id"),
		"stopped_at": (state or {}).get("stopped_at"),
	}
