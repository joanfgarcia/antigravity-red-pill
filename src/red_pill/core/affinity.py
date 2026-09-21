"""Afinidad determinista de sesión (single-writer de memoria, MULTISES-001 §3.3).

Conjunto de strings que identifica en qué proyecto/trabajo está una sesión:
`ws:<basename(workdir)>` + `mission:<mission_id>` + explícitos. Se usa como filtro
anticontaminación (semáforo de situación, pre-heating): dos sesiones afines se
ven; ajenas, no. Cero LLM, cero inferencia: lo que no está, no está.

Vacío → SILENT (sin scoping). No se inventa afinidad.
"""

from __future__ import annotations

import os
from typing import Iterable, List, Optional


def derive_affinity(
	workdir: Optional[str] = None,
	mission_id: Optional[str] = None,
	explicit: Optional[Iterable[str]] = None,
) -> List[str]:
	"""Deriva la afinidad determinista (orden estable, sin duplicados).

	- `explicit`: afinidades ya etiquetadas (env `AFFINITY`, frontmatter, payload).
	- `workdir`: CWD del IDE / `manifest.workdir` → `ws:<basename>`.
	- `mission_id`: misión en curso → `mission:<id>`.

	`ws:` para el separator final (raíz de proyecto) cae al nombre del directorio.
	"""
	out: List[str] = []
	if explicit:
		out.extend(str(a).strip() for a in explicit if str(a).strip())
	if workdir:
		base = os.path.basename(os.path.normpath(str(workdir)))
		if base and base not in (os.sep, ".", ".."):
			out.append(f"ws:{base}")
	if mission_id:
		mid = str(mission_id).strip()
		if mid:
			out.append(f"mission:{mid}")
	seen: set = set()
	dedup: List[str] = []
	for a in out:
		if a not in seen:
			seen.add(a)
			dedup.append(a)
	return dedup


def parse_affinity(raw: object) -> List[str]:
	"""Normaliza una afinidad ya almacenada (JSON list o CSV) a `list[str]`."""
	if raw is None:
		return []
	if isinstance(raw, list):
		return [str(a) for a in raw if str(a).strip()]
	text = str(raw).strip()
	if not text:
		return []
	if text.startswith("["):
		import json

		try:
			return parse_affinity(json.loads(text))
		except Exception:
			return []
	return [p.strip() for p in text.split(",") if p.strip()]
