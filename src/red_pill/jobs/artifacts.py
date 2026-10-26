"""Resultado durable de un job (RFC-INTEROP-003 S5).

El reporte efímero va al MinionInbox; el contrato estable vive en disco:

- `state/jobs/results/<job_id>.json` — autoría, estado y resumen.
- `<workspace>/.red-pill/memory/jobs/<job_id>.{json,md}` — artefacto para la siguiente alma que despierte en ese workspace.

Un job sin alma (D-02) conserva el formato con `continuity_id: null`; nunca se
inventa una identidad.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, cast

from red_pill.core.paths import get_state_dir


def _identity(task: Dict[str, Any]) -> Dict[str, str]:
	checkpoint = task.get("checkpoint_data") or {}
	payload = task.get("payload") or {}
	return {
		"continuity_id": str(task.get("continuity_id") or checkpoint.get("continuity_id") or payload.get("continuity_id") or ""),
		"parent_mission_id": str(
			task.get("parent_mission_id") or checkpoint.get("parent_mission_id") or payload.get("parent_mission_id") or ""
		),
		"originator": str(checkpoint.get("originator") or payload.get("originator") or ""),
		"role": str(checkpoint.get("role") or payload.get("role") or ("job" if task.get("continuity_id") else "")),
	}


def job_identity(task: Dict[str, Any]) -> Dict[str, str]:
	"""Identidad pública del job (para inbox, eventos y auditoría)."""
	return _identity(task)


def _workspace(task: Dict[str, Any]) -> Optional[Path]:
	payload = task.get("payload") or {}
	raw_manifest = payload.get("manifest")
	manifest = cast(Dict[str, Any], raw_manifest) if isinstance(raw_manifest, dict) else {}
	raw = payload.get("workdir") or manifest.get("workdir") or payload.get("cwd")
	if not raw:
		return None
	path = Path(str(raw)).expanduser()
	if not path.is_absolute():
		base = Path(str(payload.get("cwd") or Path.cwd())).expanduser()
		path = base / path
	path = path.resolve()
	return path if path.is_dir() else None


def _memory_root(workspace: Path) -> Path:
	"""Respeta el `memory:` custom del registro; fallback al estándar del workspace."""
	try:
		from red_pill.core.workspaces import find_workspace

		ws = find_workspace(str(workspace))
		mem_path = ws.get_memory_path if ws is not None else None
		if mem_path:
			return Path(mem_path)
	except Exception:
		pass
	return workspace / ".red-pill" / "memory"


def _write(path: Path, content: str) -> str:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_text(content, encoding="utf-8")
	os.replace(tmp, path)
	return str(path)


def build_job_result(task: Dict[str, Any], *, status: str, summary: str, error: str = "") -> Dict[str, Any]:
	identity = _identity(task)
	return {
		"job_id": str(task.get("id") or ""),
		"source": str(task.get("source") or ""),
		"status": str(status or ""),
		"summary": str(summary or ""),
		"error": str(error or ""),
		"mission_id": task.get("mission_id") or (task.get("payload") or {}).get("mission_id"),
		"continuity_id": identity["continuity_id"] or None,
		"parent_mission_id": identity["parent_mission_id"] or None,
		"originator": identity["originator"] or None,
		"role": identity["role"] or None,
		"completed_at": time.time(),
	}


def _render_notes(result: Dict[str, Any]) -> str:
	lines = [
		f"# Job {result['job_id']}",
		"",
		f"- Estado: `{result['status']}`",
		f"- Source: `{result['source']}`",
		f"- Alma: `{result.get('continuity_id') or 'sin-alma'}`",
		f"- Misión: `{result.get('parent_mission_id') or 'sin-misión'}`",
		f"- Originator: `{result.get('originator') or '-'}`",
		"",
		"## Resumen",
		"",
		result.get("summary") or "(sin resumen)",
	]
	if result.get("error"):
		lines += ["", "## Error", "", result["error"]]
	return "\n".join(lines).rstrip() + "\n"


def write_job_result(task: Dict[str, Any], *, status: str, summary: str, error: str = "") -> Dict[str, Any]:
	"""Persiste el resultado en state y, si hay workspace, en `.red-pill/memory/jobs`.

	Best-effort: un fallo de disco no debe tumbar el cierre del job. Devuelve el
	resultado con las rutas escritas (o ausentes).
	"""
	result = build_job_result(task, status=status, summary=summary, error=error)
	paths: Dict[str, str] = {}
	try:
		job_id = result["job_id"] or "unbound"
		state_path = get_state_dir() / "jobs" / "results" / f"{job_id}.json"
		paths["state_json"] = _write(state_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
	except Exception:
		pass
	workspace = _workspace(task)
	if workspace is not None:
		try:
			base = _memory_root(workspace) / "jobs"
			job_id = result["job_id"] or "unbound"
			paths["workspace_json"] = _write(base / f"{job_id}.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
			paths["workspace_notes"] = _write(base / f"{job_id}.md", _render_notes(result))
		except Exception:
			pass
	result["paths"] = paths
	return result
