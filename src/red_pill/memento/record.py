"""Registro por sesión (`_session.json`): la portada del expediente de una sesión.

Cada etapa (distill, annotate, ascensión, gate) actualiza su bloque; el fichero
vive en la raíz del directorio de sesión (`memento/<AAAA-MM>/<source>/<session>/`)
y se escribe atómicamente. El `memento_registry.json` global queda como **índice
cross-sesión** (hilo prev/next, staleness, marcado `agentic`), no como verdad: el
expediente viaja con la sesión y sobrevive a rebuilds parciales.

Estructura: un bloque por etapa bajo `stages`, más `updated_at` global:
	distill: engine, prompt_version, sections, distilled_at
	annotate: engine, annotate_prompt_version, notas, routes, flags, manifest,
		metrics, input_hash, annotated_at
	gate: stage, latest (decisión MEM-010), history (cap) — ver `memento/gating.py`
	ascend: ascendidos, last_ascended_at

Concurrencia (MEM-010 F2, hallazgo del panel adversarial): el RMW se serializa
con un lock por fichero (`flock` sobre `<name>.lock`) y la escritura usa un tmp
ÚNICO (`mkstemp`) + `os.replace`. El patrón anterior (tmp de nombre fijo) perdía
updates y crasheaba con dos escritores concurrentes (reproducido por el panel).
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

RECORD_NAME = "_session.json"


def record_path(root: Path, dir_rel: str) -> Path:
	return Path(root) / dir_rel / RECORD_NAME


def read_session_record(root: Path, dir_rel: str) -> Dict[str, Any]:
	try:
		data: Dict[str, Any] = json.loads(record_path(root, dir_rel).read_text(encoding="utf-8"))
		return data
	except (OSError, json.JSONDecodeError):
		return {}


@contextmanager
def _locked(path: Path) -> Iterator[None]:
	"""Lock exclusivo por fichero (flock sobre un `.lock` hermano)."""
	lock_path = path.with_name(path.name + ".lock")
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
	try:
		fcntl.flock(fd, fcntl.LOCK_EX)
		yield
	finally:
		fcntl.flock(fd, fcntl.LOCK_UN)
		os.close(fd)


def _write_atomic(path: Path, record: Dict[str, Any]) -> None:
	"""Escritura atómica con tmp único en el mismo directorio + replace."""
	path.parent.mkdir(parents=True, exist_ok=True)
	fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as fh:
			json.dump(record, fh, ensure_ascii=False, indent=1)
		os.replace(tmp_name, path)
	except BaseException:
		try:
			os.unlink(tmp_name)
		except OSError:
			pass
		raise


def update_session_record(root: Path, dir_rel: str, stage: str, data: Dict[str, Any]) -> None:
	"""Fusiona el bloque de una etapa y sella `updated_at` (atómico + serializado)."""
	path = record_path(root, dir_rel)
	with _locked(path):
		record = read_session_record(root, dir_rel)
		record.setdefault("stages", {})[stage] = {k: v for k, v in data.items() if v is not None}
		record["updated_at"] = datetime.now(timezone.utc).isoformat()
		_write_atomic(path, record)


def bump_session_record(root: Path, dir_rel: str, stage: str, counts: Dict[str, int]) -> None:
	"""Acumula contadores de una etapa (p.ej. ascensos) sin pisar lo anterior."""
	path = record_path(root, dir_rel)
	with _locked(path):
		record = read_session_record(root, dir_rel)
		block = record.setdefault("stages", {}).setdefault(stage, {})
		for key, value in counts.items():
			block[key] = int(block.get(key) or 0) + int(value)
		block["last_at"] = datetime.now(timezone.utc).isoformat()
		record["updated_at"] = block["last_at"]
		_write_atomic(path, record)
