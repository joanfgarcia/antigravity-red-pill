"""Cobertura del archivo Memento por sesión (raw O render).

Helper neutral (sin Qdrant ni colecciones legacy): una sesión está cubierta si
conserva `raw/` verbatim o, en su defecto, marcas renderizadas
(`memento/`/`annotate/`/`refine/`). Lo consume el migrador al single-writer para
abortar si hay memoria sin archivar antes de completar la migración.
"""

from __future__ import annotations

from pathlib import Path


def classify_session(root: Path, dir_rel: str) -> str | None:
	"""'raw' si hay copia verbatim; 'rendered' si solo marcas renderizadas; None si nada.

	`rendered` cuenta como cubierta: si la sesión está renderizada en Memento, su
	contenido se conserva aunque el store nativo se haya purgado y `raw/` esté vacío.
	"""
	d = Path(root) / dir_rel
	raw_dir = d / "raw"
	if raw_dir.is_dir() and any(raw_dir.iterdir()):
		return "raw"
	for sub in ("memento", "annotate", "refine"):
		p = d / sub
		if p.is_dir() and any(p.iterdir()):
			return "rendered"
	return None


def coverage(root: Path, registry: object | None = None) -> dict:
	"""Cobertura por sesión del registry: raw + rendered (0-100%)."""
	from red_pill.memento.registry import MementoRegistry

	reg = registry if registry is not None else MementoRegistry()
	total = 0
	raw_n = 0
	rendered_n = 0
	missing: list[str] = []
	for source, sessions in reg.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for sid, entry in sessions.items():
			dir_rel = (entry or {}).get("dir")
			if not dir_rel:
				continue
			total += 1
			kind = classify_session(root, dir_rel)
			if kind == "raw":
				raw_n += 1
			elif kind == "rendered":
				rendered_n += 1
			else:
				missing.append(f"{source}|{sid}")
	return {"total": total, "raw": raw_n, "rendered": rendered_n, "covered": raw_n + rendered_n, "missing": missing}
