"""Fragmentación y render de sesiones Memento (splits, fragmentos, frontmatter)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, NamedTuple, Optional, Tuple

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


class WorkUnit(NamedTuple):
	"""Unidad de trabajo de una sesión: un split de `memento/` (o el index entero).

	`key` es la identidad estable de la unidad (MEM-009 §2.1): el rango de
	mensajes del filename (`NNN-mensajes-0366-0443.md` → `0366-0443`), inmune a
	renumeraciones del NNN; `index` si la sesión no tiene splits. Se deriva del
	MISMO fichero y en la MISMA iteración que `nnn`/`ref`/`content`, así que
	clave y contenido no pueden desincronizarse.
	"""

	nnn: str
	ref: str
	content: str
	key: str


_RANGE_KEY_RE = re.compile(r"(\d+-\d+)$")


def _range_key(split: Path) -> str:
	m = _RANGE_KEY_RE.search(split.stem)
	return m.group(1) if m else split.stem


def work_units(session_dir: Path) -> List[WorkUnit]:
	"""Los splits de la sesión si existen; si no, el index entero (fuente única)."""
	memento_dir = session_dir / "memento"
	splits = sorted(memento_dir.glob("[0-9][0-9][0-9]-*.md"))
	units = []
	seen: set = set()
	for i, split in enumerate(splits, start=1):
		text = split.read_text(encoding="utf-8")
		first_line, _, rest = text.partition("\n")
		ref = first_line.replace("> [!ref] ", "").strip() if first_line.startswith("> [!ref]") else "memento/index.md"
		# Clave única por sesión: dos ficheros con el mismo rango (resto de un
		# re-render) fundirían sus ideas en el parcial → el repetido cae al stem.
		key = _range_key(split)
		if key in seen:
			key = split.stem
		seen.add(key)
		units.append(WorkUnit(f"{i:03d}", ref, rest.strip(), key))
	if units:
		return units
	index_text = (memento_dir / "index.md").read_text(encoding="utf-8")
	total_lines = index_text.count("\n") + 1
	return [WorkUnit("001", f"memento/index.md#l1-{total_lines}", extract_body(index_text).strip(), "index")]


# ── Fase 4 §5.4.1: partición por turnos con solape ──
# Sesiones largas exceden la ventana del LLM; en vez de recortar (pierde el
# final) se particiona por TURNOS (## ts — role) en fragmentos que quepan, con
# solape de MEMENTO_FRAGMENT_OVERLAP_MESSAGES mensajes (default 2) para no
# cortar diálogos a medias.


_TURN_RE = re.compile(r"^(## .+ — )(Usuario|Asistente|Tool|None)\s*$")
FRAGMENT_VIEWS = ("raw", "actors", "pairs")


def fragment_view(content: str, mode: str = "raw", operator: str = "Joan", agent: str = "Aleth") -> str:
	"""Vista del fragmento que ve el LLM de annotate (el árbol no cambia).

	- `raw`: tal cual (`— Usuario` / `— Asistente` / `— Tool`).
	- `actors`: mismo contenido, con el ACTOR en la cabecera de cada turno
	(`— Joan`, `— Aleth`, `— Aleth (herramienta)`). Piloto v2.1: con `— Tool` sin
	actor, el modelo atribuyó a Joan ediciones `[Code Edit]` que eran de Aleth.
	- `pairs`: solo lo que pide el operador y la respuesta FINAL del agente antes del
	siguiente mensaje del operador (sin herramientas ni mensajes intermedios),
	etiquetados. Medido 2026-09-26: conserva el 74,7% del texto del árbol.

	Solo reconoce cabeceras de turno con rol conocido al final; los `## …` dentro del
	contenido (títulos markdown) quedan como cuerpo.
	"""
	if mode not in FRAGMENT_VIEWS or mode == "raw":
		return content
	labels = {"Usuario": operator, "Asistente": agent, "Tool": f"{agent} (herramienta)", "None": "(sin rol)"}
	preamble: List[str] = []
	turns: List[Tuple[str, str, List[str]]] = []
	for line in content.split("\n"):
		m = _TURN_RE.match(line)
		if m:
			turns.append((m.group(2), m.group(1), []))
		elif turns:
			turns[-1][2].append(line)
		else:
			preamble.append(line)
	# Claude Code transporta los resultados de herramienta en mensajes con rol `user`
	# y el renderer los pinta como `— Usuario` (2026-09-26: 5.889 líneas, 169 de 178
	# "turnos del operador" de una sesión eran salidas de herramienta del agente).
	# Un turno del operador cuyo cuerpo son SOLO `[TOOL RESULT…]` es de herramienta.
	turns = [("Tool", prefix, body) if role == "Usuario" and _only_tool_results(body) else (role, prefix, body) for role, prefix, body in turns]
	if mode == "pairs":
		kept = []
		for i, turn in enumerate(turns):
			if turn[0] == "Usuario":
				kept.append(turn)
			elif turn[0] == "Asistente":
				nxt = next((t[0] for t in turns[i + 1 :] if t[0] in ("Usuario", "Asistente")), "Usuario")
				if nxt == "Usuario":
					kept.append(turn)
		turns = kept
	out = list(preamble)
	for role, prefix, body in turns:
		out.append(prefix + labels[role])
		out.extend(body)
	return "\n".join(out).strip()


def _only_tool_results(body: List[str]) -> bool:
	lines = [line for line in body if line.strip()]
	return bool(lines) and all(line.lstrip().startswith("[TOOL RESULT") for line in lines)


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
	solape de las últimas `overlap` líneas, y la cabecera repetida en cada uno.

	El presupuesto descuenta la cabecera repetida (antes un cuerpo de `max_chars`
	excedía el contrato por `len(header) + 1`). Una línea individual mayor que el
	presupuesto (JSON minificado, dump de tool) se corta por caracteres: violar
	el contexto del modelo es peor que partir una línea."""
	header, body = msg
	body_budget = max(1, max_chars - len(header) - 1)
	lines = body.split("\n")
	out: List[Tuple[str, str]] = []
	current: List[str] = []
	current_chars = 0

	def flush(*, keep_overlap: bool = True) -> None:
		nonlocal current, current_chars
		if not current:
			return
		out.append((header, "\n".join(current)))
		current = current[-overlap:] if keep_overlap and overlap > 0 else []
		current_chars = sum(len(ln) + 1 for ln in current)

	for line in lines:
		line_len = len(line) + 1
		if line_len > body_budget:
			# Línea única mayor que el presupuesto total: volcar lo pendiente y
			# partirla por caracteres (último recurso).
			flush(keep_overlap=False)
			for start in range(0, len(line), body_budget):
				out.append((header, line[start : start + body_budget]))
			current, current_chars = [], 0
			continue
		if current and current_chars + line_len > body_budget:
			flush()
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
