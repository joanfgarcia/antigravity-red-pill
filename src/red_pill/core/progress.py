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
