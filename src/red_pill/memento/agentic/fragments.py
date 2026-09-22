"""Fragmentación y render de sesiones Memento (splits, fragmentos, frontmatter)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from red_pill.memento.render import extract_body

_TITLE_SLUG_RE = re.compile(r"[^a-z0-9]+")




def _as_list(value: Any) -> List[Any]:
	"""Normaliza un campo que debería ser lista: el LLM a veces devuelve un int
	(o None, o un string) en vez de un array → iterarlo reventaba el pase (2026-09-15)."""
	if isinstance(value, list):
		return value
	if value is None:
		return []
	if isinstance(value, str):
		return [value]
	return []




def slugify_title(title: str, max_len: int = 40) -> str:
	slug = _TITLE_SLUG_RE.sub("-", title.lower()).strip("-")[:max_len].strip("-")
	return slug or "seccion"




def _work_units(session_dir: Path) -> List[Tuple[str, str, str]]:
	"""[(NNN, source_lines_ref, content)] — los splits si existen; si no, el index entero."""
	memento_dir = session_dir / "memento"
	splits = sorted(memento_dir.glob("[0-9][0-9][0-9]-*.md"))
	units = []
	for i, split in enumerate(splits, start=1):
		text = split.read_text(encoding="utf-8")
		first_line, _, rest = text.partition("\n")
		ref = first_line.replace("> [!ref] ", "").strip() if first_line.startswith("> [!ref]") else "memento/index.md"
		units.append((f"{i:03d}", ref, rest.strip()))
	if units:
		return units
	index_text = (memento_dir / "index.md").read_text(encoding="utf-8")
	total_lines = index_text.count("\n") + 1
	return [("001", f"memento/index.md#l1-{total_lines}", extract_body(index_text).strip())]




# ── Fase 4 §5.4.1: partición por turnos con solape ──
# Sesiones largas exceden la ventana del LLM; en vez de recortar (pierde el
# final) se particiona por TURNOS (## ts — role) en fragmentos que quepan, con
# solape de MEMENTO_FRAGMENT_OVERLAP_MESSAGES mensajes (default 2) para no
# cortar diálogos a medias.


def _split_messages(content: str) -> List[Tuple[str, str]]:
	"""`## ts — role\nbody` → [(header, body)]. No toca turnos que no arranquen con '## '."""
	lines = content.split("\n")
	messages: List[Tuple[str, str]] = []
	header: Optional[str] = None
	body_lines: List[str] = []
	for line in lines:
		if line.startswith("## ") and " — " in line:
			if header is not None:
				messages.append((header, "\n".join(body_lines).strip()))
			header = line
			body_lines = []
		else:
			body_lines.append(line)
	if header is not None:
		messages.append((header, "\n".join(body_lines).strip()))
	return messages




def _fragment_messages(messages: List[Tuple[str, str]], max_chars: int, overlap: int) -> List[List[Tuple[str, str]]]:
	"""Agrupa turnos en fragmentos ≤ max_chars, repitiendo los últimos `overlap`
	del fragmento anterior al inicio del siguiente (continuidad del diálogo).

	Un turno individual que EXCEDE max_chars (mensaje gigante, p.ej. un split de
	antigravity con una sola cabecera `## ts — role` y un body enorme) se
	sub-particiona por líneas con solape: la cabecera se repite en cada trozo
	para que el LLM sepa qué turno es (2026-09-15, incidente b3f27f38: 62K chars
	en un turno que no cabía en 32K)."""
	fragments: List[List[Tuple[str, str]]] = []
	current: List[Tuple[str, str]] = []
	current_chars = 0
	for msg in messages:
		msg_len = len(msg[0]) + 1 + len(msg[1])
		if current and current_chars + msg_len > max_chars:
			fragments.append(current)
			current = current[-overlap:] if overlap > 0 else []
			current_chars = sum(len(h) + 1 + len(b) for h, b in current)
		if msg_len > max_chars:
			for sub in _split_long_message(msg, max_chars, overlap):
				fragments.append([sub])
			current, current_chars = [], 0
			continue
		current.append(msg)
		current_chars += msg_len
	if current:
		fragments.append(current)
	return fragments




def _split_long_message(msg: Tuple[str, str], max_chars: int, overlap: int) -> List[Tuple[str, str]]:
	"""Sub-particiona un turno gigante por líneas: cada trozo ≤ max_chars, con
	solape de las últimas `overlap` líneas, y la cabecera repetida en cada uno."""
	header, body = msg
	lines = body.split("\n")
	out: List[Tuple[str, str]] = []
	current: List[str] = []
	current_chars = 0
	for line in lines:
		line_len = len(line) + 1
		if current and current_chars + line_len > max_chars:
			out.append((header, "\n".join(current)))
			current = current[-overlap:] if overlap > 0 else []
			current_chars = sum(len(ln) + 1 for ln in current)
		current.append(line)
		current_chars += line_len
	if current:
		out.append((header, "\n".join(current)))
	return out




def _render_fragment(fragment: List[Tuple[str, str]]) -> str:
	return "\n\n".join(f"{header}\n{body}" for header, body in fragment)




def _frontmatter_block(fields: List[Tuple[str, Any]]) -> str:
	def value_of(v: Any) -> str:
		if v is None:
			return "null"
		if isinstance(v, bool):
			return "true" if v else "false"
		if isinstance(v, (list, dict)):
			return json.dumps(v, ensure_ascii=False)
		if isinstance(v, float):
			return f"{v:.2f}"
		return json.dumps(v, ensure_ascii=False) if isinstance(v, str) and ": " in v else str(v)

	return "\n".join(["---"] + [f"{k}: {value_of(v)}" for k, v in fields] + ["---"])
