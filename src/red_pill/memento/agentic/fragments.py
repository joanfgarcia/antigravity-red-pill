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


_TURN_RE = re.compile(r"^(## .+ — )(Usuario|Asistente|Tool|Peer|None)\s*$")
FRAGMENT_VIEWS = ("raw", "actors", "pairs")


def balanced_chunks(text: str, max_chars: int) -> List[str]:
	"""Trocea en partes de tamaño SIMILAR (no 8000 + 1000), ninguna > max_chars.

	Para `annotate`, cuyas unidades son los splits de `memento/` (p50 12,2k,
	p99 24,1k chars): k = ceil(n / max_chars) trozos que apuntan a n/k chars. El
	corte se busca en una ventana alrededor del punto ideal, **eligiendo el corte
	semántico más cercano** (cabecera de turno `\n## `, luego párrafo `\n\n`,
	luego línea y por último espacio). Nunca parte una palabra, nunca supera
	`max_chars` y nunca deja un trozo residual diminuto.

	No solapa: dos trozos contiguos no repiten texto. El dedup P1-A del pase
	absorbe cualquier idea repetida entre trozos.
	"""
	import math

	n = len(text)
	if max_chars <= 0 or n <= max_chars:
		return [text]
	k = max(1, math.ceil(n / max_chars))
	target = n / k
	cuts = [0]
	for i in range(1, k):
		ideal = int(round(i * target))
		margin = max(32, int(target * 0.15))
		# El trozo i no puede pasar de max_chars ni dejar una cola imposible.
		lo = max(cuts[-1] + 1, ideal - margin, n - (k - i) * max_chars)
		hi = min(n - 1, ideal + margin, cuts[-1] + max_chars)
		if hi < lo:
			lo = hi = max(cuts[-1] + 1, min(ideal, cuts[-1] + max_chars))
		window = text[lo:hi]
		best = -1
		for marker in ("\n## ", "\n\n", "\n", " "):
			hits = []
			pos = window.find(marker)
			while pos >= 0:
				hits.append(lo + pos + (len(marker) if marker != "\n\n" else 2))
				pos = window.find(marker, pos + 1)
			if hits:
				best = min(hits, key=lambda p: abs(p - ideal))
				if marker == "\n## ":
					best -= 1  # conservar "## " al inicio del trozo
				break
		if best <= cuts[-1] or best > cuts[-1] + max_chars or best >= n:
			best = min(max(ideal, lo), hi)
		cuts.append(best)
	cuts.append(n)
	return [text[cuts[i] : cuts[i + 1]] for i in range(len(cuts) - 1)]


def fragment_view(content: str, mode: str = "raw", operator: str = "Operador", agent: str = "Agente") -> str:
	"""Vista del fragmento que ve el LLM de annotate (el árbol no cambia).

	- `raw`: tal cual (`— Usuario` / `— Asistente` / `— Tool`).
	- `actors`: mismo contenido, con el ACTOR en la cabecera de cada turno
	(etiquetas del actor: p. ej. `— <Operador>`, `— <Agente>`, `— <Agente> (herramienta)`).
	Piloto v2.1: con `— Tool` sin actor, el modelo atribuía al Operador ediciones
	`[Code Edit]` que eran del agente.
	- `pairs`: solo lo que pide el operador y la respuesta FINAL del agente antes del
	siguiente mensaje del operador (sin herramientas ni mensajes intermedios),
	etiquetados. Medido 2026-09-26: conserva el 74,7% del texto del árbol.

	Solo reconoce cabeceras de turno con rol conocido al final; los `## …` dentro del
	contenido (títulos markdown) quedan como cuerpo.
	"""
	if mode not in FRAGMENT_VIEWS or mode == "raw":
		return content
	labels = {"Usuario": operator, "Asistente": agent, "Tool": f"{agent} (herramienta)", "Peer": f"{agent} (otra sesión)", "None": "(sin rol)"}
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
	# Mensaje entre almas: llega como turno `user` y el renderer lo pinta `— Usuario`.
	# Atribuirlo al Operador fabrica autoridad: el sobre declara por escrito que no
	# viene de él (archivo 2026-10-27 lo guardó como «Usuario» igualmente).
	turns = [("Peer", prefix, body) if role == "Usuario" and _is_peer_message(body) else (role, prefix, body) for role, prefix, body in turns]
	if mode == "pairs":
		kept = []
		for i, turn in enumerate(turns):
			if turn[0] in ("Usuario", "Peer"):
				kept.append(turn)
			elif turn[0] == "Asistente":
				nxt = next((t[0] for t in turns[i + 1 :] if t[0] in ("Usuario", "Peer", "Asistente")), "Usuario")
				if nxt in ("Usuario", "Peer"):
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


def _is_peer_message(body: List[str]) -> bool:
	"""Turno `Usuario` que en realidad es un mensaje entre almas (otra sesión)."""
	from red_pill.core.speaker import PEER, classify_prompt

	text = "\n".join(body).strip()
	return bool(text) and classify_prompt(text).label == PEER


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
	"""Cabecera YAML de una nota. Todo `str` va citado con JSON (AD-151).

	La heurística vieja (citar solo si contenía ": ") dejaba escalares crudos que
	rompen el YAML: un título que empieza por backtick, por comilla simple, por
	`#`, por `- ` o por `: ` no parsea. Al no parsear, el lector lo toma por
	cuerpo y el fichero acaba con doble frontmatter (34 notas, 2026-11-28).
	JSON es subconjunto de YAML 1.2: `json.dumps` da un escalar entrecomillado
	que `yaml.safe_load` lee idéntico al original.
	"""

	def value_of(v: Any) -> str:
		if v is None:
			return "null"
		if isinstance(v, bool):
			return "true" if v else "false"
		if isinstance(v, (list, dict)):
			return json.dumps(v, ensure_ascii=False)
		if isinstance(v, float):
			return f"{v:.2f}"
		if isinstance(v, str):
			return json.dumps(v, ensure_ascii=False)
		return str(v)

	return "\n".join(["---"] + [f"{k}: {value_of(v)}" for k, v in fields] + ["---"])
