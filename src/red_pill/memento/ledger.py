"""Ledger global de rebuilds (MEM-010 F3): `state/rebuilds.json`, cap RUNS_CAP.

Una entrada por ola de gating/remediación: índice inverso run→sesiones
(`decisions`), contadores, cierre con señal (`closed`/`closed-incomplete`/
`aborted`), saneado de textos libres y modo 0600. Escritura atómica (tmp único)
con `flock`; el historial por sesión (`stages.gate.history`) es la verdad por
sesión y este índice la vista de run (sobrevive a la rotación de 10).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.memento.clean import normalize_noise
from red_pill.memento.scrub import scrub_secrets

RUNS_CAP = 10
REASON_CAP = 512
ERROR_CAP = 1024

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ABS_PATH = re.compile(r"/[^\s\"'`]+")


def ledger_path() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "rebuilds.json"


def sanitize_text(text: Any, cap: int) -> str:
	"""Contrato de saneado (MEM-010 §3.6): secretos fuera, sin ANSI/control,
	rutas absolutas reducidas a basename y cap de longitud."""
	out = normalize_noise(scrub_secrets(str(text)))
	out = _ANSI.sub("", out)
	out = _CTRL.sub("", out)
	out = _ABS_PATH.sub(lambda m: m.group(0).rstrip(".,);:]").rsplit("/", 1)[-1] or "…", out)
	return out[:cap]


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()


@contextmanager
def _locked(path: Path):
	lock_path = path.with_name(path.name + ".lock")
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
	try:
		fcntl.flock(fd, fcntl.LOCK_EX)
		yield
	finally:
		fcntl.flock(fd, fcntl.LOCK_UN)
		os.close(fd)


def _write(path: Path, runs: List[Dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as fh:
			json.dump({"runs": runs}, fh, ensure_ascii=False, indent=1)
		os.chmod(tmp_name, 0o600)
		os.replace(tmp_name, path)
	except BaseException:
		try:
			os.unlink(tmp_name)
		except OSError:
			pass
		raise


def load_runs() -> List[Dict[str, Any]]:
	try:
		data = json.loads(ledger_path().read_text(encoding="utf-8"))
		runs = data.get("runs")
		return runs if isinstance(runs, list) else []
	except (OSError, json.JSONDecodeError):
		return []


def _update(mutate) -> List[Dict[str, Any]]:
	"""RMW serializado del ledger; `mutate(runs)` in-place."""
	path = ledger_path()
	with _locked(path):
		runs = load_runs()
		mutate(runs)
		_write(path, runs)
		return runs


def _find(runs: List[Dict[str, Any]], run_id: str) -> Optional[Dict[str, Any]]:
	return next((r for r in runs if r.get("run_id") == run_id), None)


def open_run(
	*,
	run_id: str,
	stage: str,
	to_fingerprint: str,
	from_fingerprint: Optional[str] = None,
	reason: Optional[str] = None,
	job_id: Optional[str] = None,
	recipe: str = "memento_annotate_rebuild",
	policy: str = "gate-policy-v1",
) -> Dict[str, Any]:
	"""Abre (o reanuda) el run; rota a RUNS_CAP. Idempotente por run_id."""

	def mutate(runs: List[Dict[str, Any]]) -> None:
		existing = _find(runs, run_id)
		if existing is not None:
			if existing.get("status") == "open":
				existing["last_progress_at"] = _now()
			return
		runs.append(
			{
				"run_id": run_id,
				"job_id": job_id,
				"stage": stage,
				"recipe": recipe,
				"started_at": _now(),
				"finished_at": None,
				"status": "open",
				"reason": sanitize_text(reason, REASON_CAP) if reason else None,
				"from_fingerprint": from_fingerprint,
				"to_fingerprint": to_fingerprint,
				"policy_version": policy,
				"last_progress_at": _now(),
				"counts": {"processed": 0, "skipped": 0, "rescored": 0, "failed": 0},
				"decisions": {},
				"failures": {},
			}
		)
		while len(runs) > RUNS_CAP:
			runs.pop(0)

	_update(mutate)
	return _find(load_runs(), run_id) or {}


def record_decisions(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> None:
	"""Fusiona el mapa run→sesiones (saneando los motivos)."""

	def mutate(runs: List[Dict[str, Any]]) -> None:
		entry = _find(runs, run_id)
		if entry is None:
			return
		target = entry.setdefault("decisions", {})
		for dir_rel, info in decisions.items():
			target[dir_rel] = {
				"action": str((info or {}).get("action") or "?"),
				"reason": sanitize_text((info or {}).get("reason") or "", REASON_CAP),
			}
		entry["last_progress_at"] = _now()

	_update(mutate)


def set_counts(run_id: str, **absolute: int) -> None:
	def mutate(runs: List[Dict[str, Any]]) -> None:
		entry = _find(runs, run_id)
		if entry is None:
			return
		counts = entry.setdefault("counts", {})
		for key, value in absolute.items():
			counts[key] = int(value)
		entry["last_progress_at"] = _now()

	_update(mutate)


def bump_counts(run_id: str, key: str, amount: int = 1) -> None:
	def mutate(runs: List[Dict[str, Any]]) -> None:
		entry = _find(runs, run_id)
		if entry is None:
			return
		counts = entry.setdefault("counts", {})
		counts[key] = int(counts.get(key) or 0) + int(amount)
		entry["last_progress_at"] = _now()

	_update(mutate)


def record_failure(run_id: str, dir_rel: str, error: Any) -> None:
	def mutate(runs: List[Dict[str, Any]]) -> None:
		entry = _find(runs, run_id)
		if entry is None:
			return
		entry.setdefault("failures", {})[dir_rel] = sanitize_text(error, ERROR_CAP)
		entry["last_progress_at"] = _now()

	_update(mutate)


def close_stale_runs(
	except_run: Optional[str] = None,
	resolutions: Optional[Dict[str, str]] = None,
) -> List[str]:
	"""Cierra runs abiertos con la precedencia del RFC (terminalidad primero):
	`resolutions[run_id]` (calculado por quien conoce las sesiones) manda; si no,
	`closed-incomplete` conservador. Nunca toca `except_run`."""
	closed: List[str] = []

	def mutate(runs: List[Dict[str, Any]]) -> None:
		for entry in runs:
			if entry.get("status") != "open" or entry.get("run_id") == except_run:
				continue
			entry["status"] = (resolutions or {}).get(str(entry.get("run_id")), "closed-incomplete")
			entry["finished_at"] = _now()
			closed.append(str(entry.get("run_id")))

	_update(mutate)
	return closed
