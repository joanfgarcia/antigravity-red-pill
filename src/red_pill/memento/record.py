"""Registro por sesión (`_session.json`): la portada del expediente de una sesión.

Cada etapa (distill, annotate, ascensión) actualiza su bloque; el fichero vive en
la raíz del directorio de sesión (`memento/<AAAA-MM>/<source>/<session>/`) y se
escribe atómicamente. El `memento_registry.json` global queda como **índice
cross-sesión** (hilo prev/next, staleness, marcado `agentic`), no como verdad: el
expediente viaja con la sesión y sobrevive a rebuilds parciales.

Estructura: un bloque por etapa bajo `stages`, más `updated_at` global:
	distill: engine, prompt_version, sections, distilled_at
	annotate: engine, annotate_prompt_version, notas, routes, flags, annotated_at
	ascend: ascendidos, last_ascended_at
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

RECORD_NAME = "_session.json"


def record_path(root: Path, dir_rel: str) -> Path:
	return Path(root) / dir_rel / RECORD_NAME


def read_session_record(root: Path, dir_rel: str) -> Dict[str, Any]:
	try:
		data: Dict[str, Any] = json.loads(record_path(root, dir_rel).read_text(encoding="utf-8"))
		return data
	except (OSError, json.JSONDecodeError):
		return {}


def update_session_record(root: Path, dir_rel: str, stage: str, data: Dict[str, Any]) -> None:
	"""Fusiona el bloque de una etapa y sella `updated_at` (escritura atómica)."""
	record = read_session_record(root, dir_rel)
	record.setdefault("stages", {})[stage] = {k: v for k, v in data.items() if v is not None}
	record["updated_at"] = datetime.now(timezone.utc).isoformat()
	path = record_path(root, dir_rel)
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
	tmp.replace(path)


def bump_session_record(root: Path, dir_rel: str, stage: str, counts: Dict[str, int]) -> None:
	"""Acumula contadores de una etapa (p.ej. ascensos) sin pisar lo anterior."""
	record = read_session_record(root, dir_rel)
	block = record.setdefault("stages", {}).setdefault(stage, {})
	for key, value in counts.items():
		block[key] = int(block.get(key) or 0) + int(value)
	block["last_at"] = datetime.now(timezone.utc).isoformat()
	record["updated_at"] = block["last_at"]
	path = record_path(root, dir_rel)
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
	tmp.replace(path)
