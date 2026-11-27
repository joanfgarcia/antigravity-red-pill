"""Pase de títulos (AD-148): nota autocontenida → título ≤80 chars, por batches.

Separado de annotate a propósito. La extracción hace UNA cosa (el hecho); este
pase hace otra (nombrarlo) con un modelo pequeño y rápido. Evita que el juez
grande copie los ejemplos del prompt de extracción como títulos — el fallo
medido el 2026-11-27 (31-34 notas de la sesión f839399b).

Reanudable e idempotente:
- `annotate/_titles.json` guarda los títulos ya generados por batch, con el
  `text_hash` de la nota. Si el proceso muere, no se vuelve a llamar al modelo.
- El frontmatter de la nota lleva `title_version` (prompt+modelo+batch). Una
  nota titulada con otra versión, o cuyo texto cambió, se re-titula.
- Los renombrados se aplican en bloque al final; una nota sin título no se
  asciende (la regla vive en `ascension.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from . import prompts, runtime

logger = logging.getLogger(__name__)

CHECKPOINT = "_titles.json"
_FALLBACK_TITLE = ""


class TitleTooLongError(RuntimeError):
	"""Un título supera el límite DURO (120): no se trunca, se falla.

	La instrucción pide ≤80 (blando); hasta 120 se acepta tal cual. Pasarse de
	120 significa que el modelo no sirve para este carril tal como está: hay que
	cambiar prompt/modelo, no recortar la memoria.
	"""


def max_title_chars() -> int:
	import red_pill.config as cfg

	return max(20, int(getattr(cfg, "MEMENTO_TITLES_MAX_CHARS", 120) or 120))


def title_batch_size() -> int:
	import red_pill.config as cfg

	return max(1, int(getattr(cfg, "MEMENTO_TITLES_BATCH", 12) or 12))


def title_prompt_version() -> str:
	"""Firma del pase: prompt + modelo + tamaño de batch.

	Cambiar cualquiera invalida los títulos existentes (se re-titulan), igual que
	`annotate_prompt_version` invalida las notas.
	"""
	model = ""
	try:
		from red_pill.core import model_runtime as mr

		model = str(mr.resolve({"task": "titles"}).profile_name or "")
	except Exception:
		model = os.getenv("RP_LLM_MODEL", "").strip()
	return prompts.stage_signature(["titles_user"], extra={"batch": str(title_batch_size()), "model": model})


def _text_hash(text: str) -> str:
	return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
	if not text.startswith("---"):
		return {}, text
	end = text.find("\n---", 3)
	if end < 0:
		return {}, text
	try:
		fm = yaml.safe_load(text[3:end]) or {}
	except Exception:
		return {}, text
	body = text[end + 4 :].lstrip("\n")
	return (fm if isinstance(fm, dict) else {}), body


def _note_title(fm: Dict[str, Any]) -> str:
	return str(fm.get("title") or "").strip()


def _valid_title(title: str) -> bool:
	low = title.strip().lower()
	if not low:
		return False
	if re.match(r"^(conversación|revision|revisión|análisis|analisis|charla)\s+sobre\b", low):
		return False
	if re.match(r"^(joan|el operador)\s+me\s+(pide|cuenta|dice|explica|muestra)\b", low):
		return False
	return True


def _parse_titles(raw: str) -> Dict[int, str]:
	"""Array `[{"i":0,"title":"..."}]` → {índice: título válido}."""
	arr = runtime._extract_json_array(raw) or []
	out: Dict[int, str] = {}
	for row in arr if isinstance(arr, list) else []:
		if not isinstance(row, dict) or row.get("i") is None:
			continue
		try:
			i = int(row["i"])
		except (TypeError, ValueError):
			continue
		title = str(row.get("title") or "").strip()
		title = re.sub(r"\s+", " ", title)
		# Sin truncamientos (decisión del Operador, 2026-11-27): ≤80 es la
		# instrucción; hasta 120 se acepta tal cual; >120 es un fallo duro, no un
		# recorte ni un descarte silencioso.
		if len(title) > max_title_chars():
			raise TitleTooLongError(f"título de {len(title)} chars (máx {max_title_chars()}): {title[:160]}")
		if _valid_title(title):
			out[i] = title
	return out


def _call_batch(transport: runtime.Transport, batch: Sequence[Dict[str, Any]]) -> Dict[int, str]:
	"""Titula un batch; un reintento para los índices que falten o no validen."""
	import red_pill.config as cfg

	max_tokens = max(512, len(batch) * 48 + 96)
	rows = "\n\n".join(f"[{i}] {n['text'][:600]}" for i, n in enumerate(batch))
	prompt = prompts.render("titles_user", notes=rows)
	raw = transport(prompts.system("titles_user") or "", prompt, max_tokens)
	titles = _parse_titles(raw)
	missing = [i for i in range(len(batch)) if i not in titles]
	if missing:
		retry = [batch[i] for i in missing]
		rows = "\n\n".join(f"[{j}] {n['text'][:600]}" for j, n in enumerate(retry))
		prompt = prompts.render("titles_user", notes=rows)
		raw = transport(prompts.system("titles_user") or "", prompt, max(512, len(retry) * 48 + 96))
		for j, title in _parse_titles(raw).items():
			if j < len(missing):
				titles[missing[j]] = title
	if len(titles) < len(batch):
		logger.warning(f"títulos: {len(batch) - len(titles)}/{len(batch)} notas sin título válido (quedan pendientes, no ascienden)")
	return titles


def _load_checkpoint(annotate_dir: Path) -> Dict[str, Any]:
	path = annotate_dir / CHECKPOINT
	if not path.exists():
		return {"version": "", "titles": {}}
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
		return data if isinstance(data, dict) else {"version": "", "titles": {}}
	except Exception:
		return {"version": "", "titles": {}}


def _save_checkpoint(annotate_dir: Path, data: Dict[str, Any]) -> None:
	(annotate_dir / CHECKPOINT).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_note(path: Path, fm: Dict[str, Any], body: str, title: str, version: str, engine: str) -> Path:
	"""Escribe la nota con el título sellado; devuelve la ruta final (nunca pisa otra)."""
	fm = dict(fm)
	fm["title"] = title
	fm["title_version"] = version
	fm["title_engine"] = engine
	head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip()
	target = path.parent / f"{path.stem.split('-', 1)[0]}-{_slug(title)}.md"
	if target != path and target.exists():
		k = 2
		while (path.parent / f"{target.stem}-{k}.md").exists():
			k += 1
		target = path.parent / f"{target.stem}-{k}.md"
	target.write_text(f"---\n{head}\n---\n\n{body.strip()}\n", encoding="utf-8")
	if target != path:
		path.unlink(missing_ok=True)
	return target


def _slug(title: str) -> str:
	from .fragments import slugify_title

	return slugify_title(title)


def run_titles(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	transport: runtime.Transport,
) -> Dict[str, int]:
	"""Titula las notas de una sesión. Devuelve contadores (titled, skipped, pending)."""
	annotate_dir = Path(root) / dir_rel / "annotate"
	if not annotate_dir.exists():
		return {"titled": 0, "skipped": 0, "pending": 0}
	version = title_prompt_version()
	engine = runtime.served_engine()
	files = sorted(annotate_dir.glob("[0-9][0-9][0-9]-*.md"))
	notes: List[Dict[str, Any]] = []
	for path in files:
		fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
		notes.append({"path": path, "fm": fm, "text": body.strip(), "hash": _text_hash(body)})

	checkpoint = _load_checkpoint(annotate_dir)
	if checkpoint.get("version") != version:
		checkpoint = {"version": version, "titles": {}}
	stored = checkpoint.get("titles") or {}

	pending: List[Dict[str, Any]] = []
	skipped = 0
	for note in notes:
		key = note["path"].name
		fm = note["fm"]
		if str(fm.get("title_version") or "") == version and _note_title(fm):
			skipped += 1
			continue
		if key in stored and stored[key].get("hash") == note["hash"] and _valid_title(str(stored[key].get("title") or "")):
			note["title"] = str(stored[key]["title"])
			continue
		pending.append(note)

	bs = title_batch_size()
	for start in range(0, len(pending), bs):
		batch = pending[start : start + bs]
		titles = _call_batch(transport, batch)
		for i, note in enumerate(batch):
			if i in titles:
				note["title"] = titles[i]
				stored[note["path"].name] = {"hash": note["hash"], "title": titles[i]}
		checkpoint["titles"] = stored
		_save_checkpoint(annotate_dir, checkpoint)

	titled = 0
	missing = 0
	for note in notes:
		title = str(note.get("title") or "").strip()
		if not title:
			if str(note["fm"].get("title_version") or "") != version:
				missing += 1
			continue
		_write_note(note["path"], note["fm"], note["text"], title, version, engine)
		titled += 1

	_meta_path = annotate_dir / "_meta.json"
	if _meta_path.exists():
		try:
			meta = json.loads(_meta_path.read_text(encoding="utf-8"))
		except Exception:
			meta = {}
		meta["titles"] = {
			"version": version,
			"engine": engine,
			"titled_at": datetime.now(timezone.utc).isoformat(),
			"notas": titled,
			"sin_titulo": missing,
		}
		_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

	(annotate_dir / CHECKPOINT).unlink(missing_ok=True)
	logger.info(f"títulos {dir_rel}: {titled} tituladas, {skipped} ya al día, {missing} pendientes")
	return {"titled": titled, "skipped": skipped, "pending": missing}
