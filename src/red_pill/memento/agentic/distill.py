"""Distill de sesiones Memento: fragmentos → distill/NNN-*.md (RFC-002 §4.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import prompts, runtime
from .fragments import _as_list, _fragment_messages, _frontmatter_block, _render_fragment, _split_messages, _work_units, slugify_title
from .runtime import Transport


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
	`NNN-<slug>-fragmento-i-de-N.md`."""
	session_dir = root / dir_rel
	distill_dir = session_dir / "distill"
	distill_dir.mkdir(parents=True, exist_ok=True)
	for stale in distill_dir.glob("*.md"):
		stale.unlink()  # regeneración completa, jamás parcheo (§4.5.1)

	import red_pill.config as cfg

	if max_chars is None:
		max_chars = int(getattr(cfg, "MEMENTO_FRAGMENT_MAX_CHARS", 12000))
	if overlap is None:
		overlap = int(getattr(cfg, "MEMENTO_FRAGMENT_OVERLAP_MESSAGES", 2))

	sections = []
	for nnn, ref, content in _work_units(session_dir):
		if len(content) <= max_chars:
			frag_parts = [(content, 1, 1)]
		else:
			messages = _split_messages(content)
			frags = _fragment_messages(messages, max_chars, overlap)
			frag_parts = [(_render_fragment(f), i, len(frags)) for i, f in enumerate(frags, 1)]

		prev_summary = ""
		for frag_text, i, total in frag_parts:
			if total > 1 and i > 1:
				prompt = prompts.DISTILL_USER_CONTINUATION.format(voice=prompts._VOICE_RULE, previous=prev_summary or "(ninguno)", content=frag_text)
			else:
				prompt = prompts.DISTILL_USER_OPENING.format(voice=prompts._VOICE_RULE, content=frag_text)
			raw = transport(prompts.DISTILL_SYSTEM, prompt, 512)
			parsed = runtime._extract_json(raw) or {}
			title = str(parsed.get("title") or f"Sección {nnn}")[:80]
			summary = str(parsed.get("summary") or frag_text[:400]).strip()
			keywords = [str(k) for k in _as_list(parsed.get("keywords"))][:8]
			slug = slugify_title(title)

			fields = [
				("session_id", session_id),
				("source", source),
				("section", int(nnn)),
				("title", title),
				("keywords", keywords),
				("source_lines", ref),
				("source_ref", "memento/index.md"),
				("engine", runtime.engine_id()),
				("prompt_version", runtime.distill_prompt_version()),
			]
			if total > 1:
				filename = f"{nnn}-{slug}-fragmento-{i}-de-{total}.md"
				fields.insert(3, ("fragment", i))
				fields.insert(4, ("fragments_total", total))
				fields.insert(5, ("fragment_of", str(nnn)))
			else:
				filename = f"{nnn}-{slug}.md"
			(distill_dir / filename).write_text(f"{_frontmatter_block(fields)}\n\n{summary}\n", encoding="utf-8")
			sections.append(
				{
					"nnn": nnn,
					"file": filename,
					"title": title,
					"summary": summary,
					"source_lines": ref,
					"fragment": i if total > 1 else None,
					"fragments_total": total if total > 1 else None,
				}
			)
			prev_summary = summary
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
