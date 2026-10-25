"""Write-ahead de turnos en arneses externos (B-01h).

Los hooks de opencode/claude/pi no pueden importar el kernel (viven fuera del
repo). Dejan un journal JSON atómico por turno; el kernel lo importa al espejo
cuando despierta o cuando el Operador inspecciona `session pending`.

Garantía: la intención (`prompt`) queda en disco **antes** de invocar al modelo.
No promete exactly-once de efectos cloud (B-04): un proceso muerto deja el
turno `pending`/`aborted`, nunca un `completed` inventado.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.core.paths import get_state_dir

CURRENT_DIR = "external_turns/current"
ARCHIVE_DIR = "external_turns/archive"


def _now() -> float:
	return time.time()


def _safe(token: str) -> str:
	return str(token or "").strip().replace("/", "_").replace("__", "_").replace(":", "_")


def _root() -> Path:
	return get_state_dir()


def current_path(provider: str, session_id: str) -> Path:
	return _root() / CURRENT_DIR / f"{_safe(provider)}__{_safe(session_id)}.json"


def archive_path(provider: str, session_id: str, request_id: str) -> Path:
	return _root() / ARCHIVE_DIR / f"{_safe(provider)}__{_safe(session_id)}__{_safe(request_id)}.json"


def _write(path: Path, data: Dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	os.replace(tmp, path)


def _read(path: Path) -> Optional[Dict[str, Any]]:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None
	return data if isinstance(data, dict) else None


def begin_external_turn(
	*,
	provider: str,
	session_id: str,
	prompt: str,
	cwd: str = "",
	originator: Optional[str] = None,
	model: Optional[str] = None,
	request_id: Optional[str] = None,
) -> Dict[str, Any]:
	"""Persiste la intención del turno antes del modelo (idempotente por sesión)."""
	provider = str(provider or "").strip()
	session = str(session_id or "").strip()
	if not provider or not session:
		raise ValueError("provider y session_id requeridos")
	path = current_path(provider, session)
	previous = _read(path)
	if previous and str(previous.get("status") or "") == "pending":
		if str(previous.get("prompt") or "") == str(prompt or ""):
			return previous
		# Un turno nuevo sin Stop del anterior: el anterior queda abortado, no se pisa.
		previous.update({"status": "aborted", "reason": "superseded", "ended_at": _now()})
		_write(archive_path(provider, session, str(previous.get("request_id") or "unknown")), previous)
	stamp = _now()
	request = str(request_id or f"{provider}:{session}:{int(stamp * 1000)}:{uuid.uuid4().hex[:8]}")
	data = {
		"provider": provider,
		"session_id": session,
		"originator": str(originator or f"{provider}:{session}"),
		"request_id": request,
		"prompt": str(prompt or ""),
		"cwd": str(cwd or ""),
		"model": str(model or "") or None,
		"started_at": stamp,
		"status": "pending",
	}
	_write(path, data)
	return data


def finish_external_turn(
	*,
	provider: str,
	session_id: str,
	status: str = "completed",
	response: str = "",
	reason: str = "",
	model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
	"""Cierra el turno actual y lo archiva; `None` si no había intención."""
	provider = str(provider or "").strip()
	session = str(session_id or "").strip()
	if not provider or not session:
		return None
	if status not in ("completed", "aborted"):
		status = "aborted"
	path = current_path(provider, session)
	data = _read(path)
	if not data:
		return None
	data.update(
		{
			"status": status,
			"response": str(response or ""),
			"reason": str(reason or "") or None,
			"model": str(model or data.get("model") or "") or None,
			"ended_at": _now(),
		}
	)
	_write(archive_path(provider, session, str(data.get("request_id") or "unknown")), data)
	try:
		path.unlink()
	except FileNotFoundError:
		pass
	return data


def _journals(root: Optional[Path] = None) -> List[Path]:
	root = Path(root) if root is not None else _root()
	paths: List[Path] = []
	for sub in (CURRENT_DIR, ARCHIVE_DIR):
		directory = root / sub
		try:
			paths.extend(sorted(p for p in directory.iterdir() if p.suffix == ".json"))
		except (FileNotFoundError, NotADirectoryError):
			continue
	return paths


def import_external_turns(
	*,
	limit: int = 100,
	mirror: Any = None,
	registry: Any = None,
	root: Optional[Path] = None,
) -> Dict[str, int]:
	"""Importa journals al espejo SOLO si el originator ya tiene alma registrada.

	Sin fila en `session_registry` no se inventa `continuity_id`: el journal se
	queda para el siguiente despertar. Idempotente por `request_id`.
	"""
	from red_pill.session.mirror import SessionMirror
	from red_pill.session.store import SessionRegistry

	mirror = mirror or SessionMirror()
	registry = registry or SessionRegistry()
	counts = {"pending": 0, "completed": 0, "aborted": 0, "skipped": 0}
	for path in _journals(root)[:limit]:
		data = _read(path)
		if not data:
			counts["skipped"] += 1
			continue
		originator = str(data.get("originator") or "")
		row = registry.get_by_originator(originator) if originator else None
		continuity = str((row or {}).get("continuity_id") or "")
		mission = str((row or {}).get("mission_id") or "")
		if not continuity or not mission:
			counts["skipped"] += 1
			continue
		request = str(data.get("request_id") or "")
		prompt = str(data.get("prompt") or "")
		status = str(data.get("status") or "pending")
		try:
			mirror.begin_turn(
				continuity_id=continuity,
				mission_id=mission,
				request_id=request,
				content=prompt,
				originator=originator,
				source="external_hook",
				model=str(data.get("model") or "") or None,
				ts=float(data.get("started_at") or _now()),
				source_ref=f"{request}:user",
			)
			response = str(data.get("response") or "")
			if status == "completed":
				if response:
					mirror.append_turn(
						continuity_id=continuity,
						mission_id=mission,
						role="assistant",
						content=response,
						originator=originator,
						source="external_hook",
						source_ref=f"{request}:response",
						request_id=request,
						status="completed",
					)
				mirror.complete_turn(continuity_id=continuity, request_id=request)
				counts["completed"] += 1
			elif status == "aborted":
				mirror.abort_turn(
					continuity_id=continuity,
					request_id=request,
					reason=str(data.get("reason") or "external_aborted"),
					partial_response=response or None,
					mission_id=mission,
				)
				counts["aborted"] += 1
			else:
				counts["pending"] += 1
		except Exception:
			counts["skipped"] += 1
			continue
		# Un pending de la sesión viva se conserva (idempotente); los cerrados ya
		# están en el espejo y no necesitan reimportarse.
		if status != "pending":
			try:
				path.unlink()
			except FileNotFoundError:
				pass
	return counts
