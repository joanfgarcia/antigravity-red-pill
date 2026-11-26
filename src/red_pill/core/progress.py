"""Fine-grained job progress channel (RFC-JOBDAG-002 Phase 4).

Neutral module (no dependency on `jobs.drivers`): a long-running stage publishes
progress by calling `report_stage_progress()`, which writes to `$RP_PROGRESS_FILE`
outside the DB. Any driver enables the channel for its child process with
`enable_stage_progress(env, job_id)` — one helper, uniform for script/element/dag.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, cast

RP_PROGRESS_FILE = "RP_PROGRESS_FILE"


def atomic_write_text(path: Path, text: str) -> None:
	"""Write `text` to `path` atomically via a UNIQUE temp file (O_EXCL, no symlink race)."""
	path.parent.mkdir(parents=True, exist_ok=True)
	fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as fh:
			fh.write(text)
		os.replace(tmp_name, path)
	except Exception:
		try:
			os.unlink(tmp_name)
		except OSError:
			pass
		raise


def job_progress_path(job_id: str) -> Path:
	"""Control file: fine intra-stage progress + forensic detail (outside the DB)."""
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "jobs" / f"{(job_id or 'unbound')[:8]}.progress.json"


def write_job_progress(job_id: str, data: Dict[str, Any]) -> None:
	"""Write (atomic, best-effort) the job progress file."""
	try:
		atomic_write_text(job_progress_path(job_id), json.dumps(data, ensure_ascii=False))
	except Exception:
		pass


def read_job_progress(job_id: str) -> Optional[Dict[str, Any]]:
	"""Read the job progress file (None if absent or unreadable)."""
	try:
		path = job_progress_path(job_id)
		if path.is_file():
			return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
	except Exception:
		pass
	return None


# ── Historial de duración por etapa (para el ETA del dag_job) ──────────────
# El ETA ingenua (`etapas restantes × último step`) miente cuando el último step
# fue un lote de fan-out de 28 min y las etapas que quedan son rituales de 3 s
# (job 6028d497: 9 h 46 min anunciadas para un ciclo de ~1 h). Aquí se guarda la
# duración observada de CADA hoja, por misión, y el ETA suma la mediana de las
# que faltan. Ver `.red-pill/memory/NOTE_2026-11-25_eta-job-manager.md`.
STAGE_STATS_FILE = "job_stage_stats.json"
STAGE_STATS_HISTORY = 15


def _stage_stats_path() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / STAGE_STATS_FILE


def _read_stage_stats() -> Dict[str, Dict[str, list]]:
	try:
		path = _stage_stats_path()
		if path.is_file():
			data = json.loads(path.read_text(encoding="utf-8"))
			if isinstance(data, dict):
				return data
	except Exception:
		pass
	return {}


def record_stage_durations(mission_id: str, durations: Dict[str, float], limit: int = STAGE_STATS_HISTORY) -> None:
	"""Anota la duración observada de cada etapa ejecutada (best-effort, no rompe)."""
	if not mission_id or not durations:
		return
	try:
		data = _read_stage_stats()
		bucket = data.setdefault(str(mission_id), {})
		for stage_path, seconds in durations.items():
			try:
				value = round(float(seconds), 2)
			except (TypeError, ValueError):
				continue
			if value <= 0:
				continue
			series = list(bucket.get(str(stage_path)) or [])
			series.append(value)
			bucket[str(stage_path)] = series[-limit:]
		atomic_write_text(_stage_stats_path(), json.dumps(data, ensure_ascii=False))
	except Exception:
		pass


def stage_duration_medians(mission_id: str) -> Dict[str, float]:
	"""Mediana por etapa observada en ejecuciones anteriores de la misma misión."""
	import statistics

	bucket = (_read_stage_stats().get(str(mission_id)) or {}) if mission_id else {}
	out: Dict[str, float] = {}
	for stage_path, series in bucket.items():
		values = [float(v) for v in (series or []) if isinstance(v, (int, float)) and v > 0]
		if values:
			out[str(stage_path)] = float(statistics.median(values))
	return out



def job_progress_age_s(job_id: str) -> Optional[float]:
	"""Segundos desde el último latido del fichero (None si no existe o no se puede leer).

	El latido no es el `updated_at` de la DB — ese solo cambia en frontera de step y
	se congela durante horas en las etapas largas. El fichero lo reescribe el hijo
	mientras trabaja: su mtime es la única prueba de vida fina.
	"""
	try:
		path = job_progress_path(job_id)
		if not path.is_file():
			return None
		return max(0.0, time.time() - path.stat().st_mtime)
	except Exception:
		return None


def report_stage_progress(**data: Any) -> None:
	"""Publish fine progress to `$RP_PROGRESS_FILE` (no-op if the channel is off).

	Called by long stages; best-effort atomic — telemetry never breaks the work.
	Field convention for the render: `label`, `current`, `total`.
	"""
	path = os.environ.get(RP_PROGRESS_FILE)
	if not path:
		return
	try:
		data.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
		atomic_write_text(Path(path), json.dumps(data, ensure_ascii=False))
	except Exception:
		pass


def enable_stage_progress(env: Dict[str, str], job_id: str) -> Dict[str, str]:
	"""Enable the fine-progress channel for a child: point `$RP_PROGRESS_FILE` at it.

	Clears any stale file from a previous run. Returns `env` for chaining.
	"""
	if not job_id:
		return env
	ppath = job_progress_path(job_id)
	try:
		ppath.unlink(missing_ok=True)
	except OSError:
		pass
	env[RP_PROGRESS_FILE] = str(ppath)
	return env
