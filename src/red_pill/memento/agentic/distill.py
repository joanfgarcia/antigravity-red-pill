"""Distill de sesiones Memento: fragmentos → distill/NNN-*.md (RFC-002 §4.5).

Reuso incremental por unidad (NB-001 F2a, D-NB-03/08/09/11): con
`MEMENTO_DISTILL_REUSE_ENABLED` (RULE 4, default OFF), el manifest persistente
`distill/_meta.json` guarda por `unit_key` (rango de mensajes) el `content_hash`
del cuerpo + prompt_version/engine/fragmentación, y reusa las secciones intactas
entre noches en vez de borrar y rehacer. OFF → regeneración completa (histórico).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import prompts, runtime
from .fragments import (
	WorkUnit,
	_as_list,
	_fragment_messages,
	_frontmatter_block,
	_render_fragment,
	_split_messages,
	slugify_title,
	work_units,
)
from .runtime import Transport

MANIFEST_SCHEMA = "distill-reuse-v1"
_MANIFEST = "_meta.json"


def _load_manifest(distill_dir: Path) -> Dict[str, Any]:
	"""Manifest de reuso por `unit_key`, o vacío si no existe / es ilegible."""
	path = distill_dir / _MANIFEST
	if not path.exists():
		return {}
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}
	units = data.get("units") if isinstance(data, dict) else None
	return dict(units) if isinstance(units, dict) else {}


def _seed_manifest(
	distill_dir: Path,
	units: List[WorkUnit],
	prompt_version: str,
	engine: str,
	max_chars: int,
	overlap: int,
) -> Dict[str, Any]:
	"""Siembra (D-NB-11): primera noche tras F2, sin manifest — se adopta la
	sección existente sólo si sus fragmentos declaran el `prompt_version` y el
	`engine` vigentes (clave = `section`/posición). Lo demás se re-destila."""
	from red_pill.memento.ascension import parse_refine
	from red_pill.memento.render import compute_hash

	by_section: Dict[str, List[str]] = {}
	for f in distill_dir.glob("*.md"):
		try:
			fm, _ = parse_refine(f.read_text(encoding="utf-8"))
		except Exception:
			continue
		section = fm.get("section")
		if section is None:
			continue
		if fm.get("prompt_version") != prompt_version or fm.get("engine") != engine:
			continue
		by_section.setdefault(f"{int(section):03d}", []).append(f.name)

	seeded: Dict[str, Any] = {}
	for unit in units:
		files = by_section.get(unit.nnn)
		if not files:
			continue
		seeded[unit.key] = {
			"content_hash": compute_hash(unit.content),
			"prompt_version": prompt_version,
			"engine": engine,
			"fragment_max_chars": max_chars,
			"fragment_overlap": overlap,
			"degraded": False,
			"files": files,
		}
	return seeded


def _write_manifest(distill_dir: Path, units: Dict[str, Any]) -> None:
	from red_pill.memento.record import write_json_atomic

	write_json_atomic(distill_dir / _MANIFEST, {"schema": MANIFEST_SCHEMA, "units": units})


def _section_fields(
	session_id: str,
	source: str,
	nnn: str,
	title: str,
	keywords: List[str],
	ref: str,
	engine: str,
	trust: str,
	prompt_version: str,
	*,
	fragment: Optional[int] = None,
	fragments_total: Optional[int] = None,
	fragment_of: Optional[str] = None,
	unit_key: Optional[str] = None,
	degraded: bool = False,
) -> List[Tuple[str, Any]]:
	"""Frontmatter de una sección distill, en el MISMO orden que el contrato
	histórico; `unit_key`/`degraded` solo cuando el reuso está activo."""
	fields: List[Tuple[str, Any]] = [
		("session_id", session_id),
		("source", source),
		("section", int(nnn)),
	]
	if unit_key is not None:
		fields.append(("unit_key", unit_key))
	if fragment is not None:
		fields.append(("fragment", fragment))
		fields.append(("fragments_total", fragments_total))
		fields.append(("fragment_of", str(fragment_of)))
	fields += [
		("title", title),
		("keywords", keywords),
		("source_lines", ref),
		("source_ref", "memento/index.md"),
		("engine", engine),
		("trust", trust),
		("prompt_version", prompt_version),
	]
	if degraded:
		fields.append(("degraded", True))
	return fields


def _distill_unit(
	distill_dir: Path,
	unit: WorkUnit,
	session_id: str,
	source: str,
	transport: Transport,
	max_chars: int,
	overlap: int,
	reuse_mode: bool,
) -> Tuple[List[Dict[str, Any]], List[str], bool]:
	"""Distila UN work unit → escribe sus ficheros. Devuelve (sections, filenames, degraded).

	`reuse_mode` (flag ON) añade los campos F2a (`unit_key`, `degraded`) al
	frontmatter; OFF deja el contrato histórico byte-idéntico.
	"""
	nnn, ref, content = unit.nnn, unit.ref, unit.content
	unit_key = unit.key if reuse_mode else None
	engine = runtime.engine_id()
	prompt_version = runtime.distill_prompt_version()
	trust = runtime.model_trust()
	if len(content) <= max_chars:
		frag_parts = [(content, 1, 1)]
	else:
		messages = _split_messages(content)
		frags = _fragment_messages(messages, max_chars, overlap)
		frag_parts = [(_render_fragment(f), i, len(frags)) for i, f in enumerate(frags, 1)]

	sections: List[Dict[str, Any]] = []
	filenames: List[str] = []
	degraded = False
	prev_summary = ""
	for frag_text, i, total in frag_parts:
		if total > 1 and i > 1:
			prompt = prompts.render("distill_user_continuation", previous=prev_summary or "(ninguno)", content=frag_text)
		else:
			prompt = prompts.render("distill_user_opening", content=frag_text)
		raw = transport(prompts.system("distill_user_opening") or "", prompt, 512)
		if runtime.is_degraded(raw):
			degraded = True
		parsed = runtime._extract_json(raw) or {}
		title = str(parsed.get("title") or f"Sección {nnn}")[:80]
		summary = str(parsed.get("summary") or frag_text[:400]).strip()
		keywords = [str(k) for k in _as_list(parsed.get("keywords"))][:8]
		slug = slugify_title(title)

		fragment: Optional[int]
		fragments_total: Optional[int]
		fragment_of: Optional[str]
		if total > 1:
			filename = f"{nnn}-{slug}-fragmento-{i}-de-{total}.md"
			fragment, fragments_total, fragment_of = i, total, str(nnn)
		else:
			filename = f"{nnn}-{slug}.md"
			fragment = fragments_total = fragment_of = None

		fields = _section_fields(
			session_id,
			source,
			nnn,
			title,
			keywords,
			ref,
			engine,
			trust,
			prompt_version,
			fragment=fragment,
			fragments_total=fragments_total,
			fragment_of=fragment_of,
			unit_key=unit_key,
			degraded=degraded and reuse_mode,
		)
		(distill_dir / filename).write_text(f"{_frontmatter_block(fields)}\n\n{summary}\n", encoding="utf-8")
		section: Dict[str, Any] = {
			"nnn": nnn,
			"file": filename,
			"title": title,
			"summary": summary,
			"source_lines": ref,
			"fragment": i if total > 1 else None,
			"fragments_total": total if total > 1 else None,
		}
		if unit_key is not None:
			section["unit_key"] = unit_key
		sections.append(section)
		filenames.append(filename)
		prev_summary = summary
	return sections, filenames, degraded


def _refresh_unit(
	distill_dir: Path,
	unit: WorkUnit,
	session_id: str,
	source: str,
	entry: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
	"""Reusa una unidad ya destilada: refresca `nnn`/`source_lines` (sin LLM) y
	renombra el fichero si cambió el `nnn`. No se pierde ningún fragmento."""
	from red_pill.memento.ascension import parse_refine

	nnn, ref = unit.nnn, unit.ref
	unit_key = unit.key
	engine = runtime.engine_id()
	prompt_version = runtime.distill_prompt_version()
	sections: List[Dict[str, Any]] = []
	filenames: List[str] = []
	for old_name in entry.get("files") or []:
		old_path = distill_dir / old_name
		if not old_path.exists():
			continue
		try:
			fm, body = parse_refine(old_path.read_text(encoding="utf-8"))
		except Exception:
			continue
		title = str(fm.get("title") or f"Sección {nnn}")[:80]
		slug = slugify_title(title)
		keywords = [str(k) for k in _as_list(fm.get("keywords"))][:8]
		fragment = fm.get("fragment")
		fragments_total = fm.get("fragments_total")
		fragment_of = fm.get("fragment_of")
		if fragment is not None and fragments_total is not None:
			filename = f"{nnn}-{slug}-fragmento-{int(fragment)}-de-{int(fragments_total)}.md"
		else:
			filename = f"{nnn}-{slug}.md"
		# El contenido lo escribió el motor viejo: conserva su `engine`/`trust`
		# (no se re-atribuye al motor vigente); `prompt_version` ya coincide.
		fields = _section_fields(
			session_id,
			source,
			nnn,
			title,
			keywords,
			ref,
			str(fm.get("engine") or engine),
			str(fm.get("trust") or runtime.model_trust()),
			str(fm.get("prompt_version") or prompt_version),
			fragment=fragment,
			fragments_total=fragments_total,
			fragment_of=fragment_of,
			unit_key=unit_key,
			degraded=False,
		)
		new_path = distill_dir / filename
		if new_path != old_path:
			old_path.unlink(missing_ok=True)
		new_path.write_text(f"{_frontmatter_block(fields)}\n\n{body}\n", encoding="utf-8")
		filenames.append(filename)
		sections.append(
			{
				"nnn": nnn,
				"file": filename,
				"title": title,
				"summary": body,
				"source_lines": ref,
				"fragment": int(fragment) if fragment is not None else None,
				"fragments_total": int(fragments_total) if fragments_total is not None else None,
				"unit_key": unit_key,
			}
		)
	return sections, filenames


def _can_reuse(
	entry: Optional[Dict[str, Any]],
	content_hash: str,
	prompt_version: str,
	engine: str,
	max_chars: int,
	overlap: int,
	distill_dir: Path,
) -> bool:
	"""Reuso solo si coinciden TODOS los campos y la sección no está `degraded`
	ni ha perdido ficheros (D-NB-03)."""
	if not entry:
		return False
	if entry.get("degraded"):
		return False
	if entry.get("content_hash") != content_hash:
		return False
	if entry.get("prompt_version") != prompt_version:
		return False
	if entry.get("engine") != engine:
		return False
	if entry.get("fragment_max_chars") != max_chars:
		return False
	if entry.get("fragment_overlap") != overlap:
		return False
	files = entry.get("files") or []
	if not files:
		return False
	return all((distill_dir / f).exists() for f in files)


def _distill_reusing(
	distill_dir: Path,
	units: List[WorkUnit],
	session_id: str,
	source: str,
	transport: Transport,
	max_chars: int,
	overlap: int,
) -> List[Dict[str, Any]]:
	"""Camino F2a (flag ON): manifest persistente + reuso por unidad + huérfanos al final."""
	from red_pill.core.progress import report_stage_progress
	from red_pill.memento.render import compute_hash

	engine = runtime.engine_id()
	prompt_version = runtime.distill_prompt_version()

	manifest = _load_manifest(distill_dir)
	current_keys = {unit.key for unit in units}
	if manifest:
		# Rangos desaparecidos se descartan del manifest; sus ficheros (huérfanos)
		# se retiran al final, tras escribir el manifest (D-NB-03/08).
		manifest = {k: v for k, v in manifest.items() if k in current_keys}
	else:
		manifest = _seed_manifest(distill_dir, units, prompt_version, engine, max_chars, overlap)

	new_units = dict(manifest)
	sections: List[Dict[str, Any]] = []
	for i_unit, unit in enumerate(units, 1):
		report_stage_progress(label="distill", current=i_unit, total=len(units), session=session_id)
		unit_key = unit.key
		content_hash = compute_hash(unit.content)

		if _can_reuse(new_units.get(unit_key), content_hash, prompt_version, engine, max_chars, overlap, distill_dir):
			unit_sections, filenames = _refresh_unit(distill_dir, unit, session_id, source, new_units[unit_key])
			sections.extend(unit_sections)
			new_units[unit_key] = {
				"content_hash": content_hash,
				"prompt_version": prompt_version,
				"engine": engine,
				"fragment_max_chars": max_chars,
				"fragment_overlap": overlap,
				"degraded": False,
				"files": filenames,
			}
		else:
			unit_sections, filenames, degraded = _distill_unit(
				distill_dir, unit, session_id, source, transport, max_chars, overlap, reuse_mode=True
			)
			sections.extend(unit_sections)
			new_units[unit_key] = {
				"content_hash": content_hash,
				"prompt_version": prompt_version,
				"engine": engine,
				"fragment_max_chars": max_chars,
				"fragment_overlap": overlap,
				"degraded": degraded,
				"files": filenames,
			}
		# Manifest incremental: un kill pierde como mucho la unidad en vuelo.
		_write_manifest(distill_dir, new_units)

	# Huérfanos (rangos desaparecidos) al final, tras el manifest.
	valid = {name for e in new_units.values() for name in e.get("files") or []}
	for stale in distill_dir.glob("*.md"):
		if stale.name not in valid:
			stale.unlink()

	return sections


def distill_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	transport: Transport,
	max_chars: Optional[int] = None,
	overlap: Optional[int] = None,
) -> List[Dict[str, Any]]:
	"""Escribe distill/NNN-<slug>.md por unidad de trabajo. → metadatos de las secciones.

	Si un work unit excede `max_chars` (presupuesto de contexto), se particiona por
	turnos con solape (`overlap` mensajes) y se distilla un fragmento por parte
	con prompt por posición (Fase 4 §5.4.1). Los fragmentos se marcan
	`fragment`/`fragments_total`/`fragment_of` y se nombran
	`NNN-<slug>-fragmento-i-de-N.md`.

	Con `MEMENTO_DISTILL_REUSE_ENABLED` (F2a), la unidad es el RANGO de mensajes
	(`unit_key`) y las secciones intactas se reusan entre noches; OFF → borrar y
	rehacer (comportamiento histórico exacto).
	"""
	session_dir = root / dir_rel
	distill_dir = session_dir / "distill"
	distill_dir.mkdir(parents=True, exist_ok=True)

	import red_pill.config as cfg
	from red_pill.core.progress import report_stage_progress

	if max_chars is None:
		max_chars = int(getattr(cfg, "MEMENTO_FRAGMENT_MAX_CHARS", 12000))
	if overlap is None:
		overlap = int(getattr(cfg, "MEMENTO_FRAGMENT_OVERLAP_MESSAGES", 2))

	# RULE 4: lectura única del flag de reuso por unidad (NB-001 F2a).
	reuse_enabled = bool(getattr(cfg, "MEMENTO_DISTILL_REUSE_ENABLED", False))

	units = list(work_units(session_dir))

	if not reuse_enabled:
		for stale in distill_dir.glob("*.md"):
			stale.unlink()  # regeneración completa, jamás parcheo (§4.5.1)
		sections: List[Dict[str, Any]] = []
		for i_unit, unit in enumerate(units, 1):
			report_stage_progress(label="distill", current=i_unit, total=len(units), session=session_id)
			unit_sections, _filenames, _degraded = _distill_unit(
				distill_dir, unit, session_id, source, transport, max_chars, overlap, reuse_mode=False
			)
			sections.extend(unit_sections)
	else:
		sections = _distill_reusing(distill_dir, units, session_id, source, transport, max_chars, overlap)

	from datetime import datetime, timezone

	from red_pill.memento.record import update_session_record

	update_session_record(
		root,
		dir_rel,
		"distill",
		{
			"engine": runtime.engine_id(),
			"prompt_version": runtime.distill_prompt_version(),
			"sections": len(sections),
			"distilled_at": datetime.now(timezone.utc).isoformat(),
		},
	)
	return sections
