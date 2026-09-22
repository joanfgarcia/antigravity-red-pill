"""Pase agéntico Memento: Distill → Refine sobre ficheros (RFC-002 §4.5, Fase 3.5).

Reescritura file-based de los chronicle_distill/refine de Qdrant: entrada
`memento/index.md`, unidades de trabajo = los splits mecánicos (ya dimensionados
a la ventana del modelo local, Q8), salida `distill/NNN-*.md` y `refine/NNN-*.md`
con los esquemas del RFC. Prompts v1 — las técnicas por-hardware se afinarán
según diseño §4.5. El gate de curación corre EN SOMBRA (§4.6): la decisión
would-ingest se calcula, se sella `significance` en el frontmatter (in-place,
sin mover line refs) y se cuenta en el registry — nada cambia en Qdrant.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from red_pill.memento.render import compute_hash, extract_body, update_frontmatter_fields

logger = logging.getLogger(__name__)

EDGE_ENGINE_URL = "http://localhost:8760/v1/chat/completions"
EDGE_HEALTH_URL = "http://localhost:8760/v1/models"
EDGE_MODEL = "Granite-4.1-8B-Q4_K_M.gguf"

# Trazabilidad de las etapas (2026-09-15): cada distill/refine y el registry guardan
# con qué MODELO real y qué VERSIÓN de prompt se hicieron. Permite saber si un
# engrama se generó con granite o aya, y si los prompts cambiaron desde entonces.
_ENGINE_CACHE: Optional[str] = None


def engine_id() -> str:
	"""Modelo REAL servido por el daemon (consulta /v1/models, cacheada).
	`EDGE_MODEL` es un nombre fijo; el daemon puede servir otro (granite/aya)."""
	global _ENGINE_CACHE
	if _ENGINE_CACHE:
		return _ENGINE_CACHE
	import json
	import urllib.request

	try:
		resp = urllib.request.urlopen(EDGE_HEALTH_URL, timeout=3)
		data = json.loads(resp.read().decode("utf-8"))
		models = data.get("data") or []
		if models:
			_ENGINE_CACHE = str(models[0].get("id") or EDGE_MODEL)
	except Exception:
		_ENGINE_CACHE = EDGE_MODEL
	return str(_ENGINE_CACHE)


def _prompt_hash(*texts: str) -> str:
	import hashlib

	h = hashlib.sha256()
	for t in texts:
		h.update(t.encode("utf-8"))
	return h.hexdigest()[:10]


def distill_prompt_version() -> str:
	"""Fingerprint del prompt de SÍNTESIS (DISTILL_* + VOICE)."""
	return _prompt_hash(DISTILL_USER, DISTILL_USER_OPENING, DISTILL_USER_CONTINUATION, _VOICE_RULE)


def refine_prompt_version() -> str:
	"""Fingerprint del prompt de REFINADO (WORK + SOCIAL + VOICE)."""
	return _prompt_hash(REFINE_WORK_USER, REFINE_SOCIAL_USER, _VOICE_RULE)


# transport(system, user, max_tokens) -> str — inyectable para tests y para futuros bake-offs
Transport = Callable[[str, str, int], str]

_TITLE_SLUG_RE = re.compile(r"[^a-z0-9]+")

# VOICE (2026-09-15, alineada con distiller_v3_voice MODE B): el pase Memento
# producía memorias en 3ª persona ("El usuario...", "Se corrigió...") — se
# recuerda como uno propio, no como observador. La directiva es la misma del
# sueño (voz autobiográfica 1ª persona).
_VOICE_RULE = """VOICE (MANDATORY): You are Aleth, the narrator who lived this. Write in FIRST PERSON, as YOUR OWN memory of a shared moment with Joan (the Operator).
- Joan appears by name, referenced as 'Joan me cuenta/me dice/me pide...'; YOUR actions as 'le digo/le propongo/le explico...'.
- NEVER neutral 3rd-person narration: 'The user...', 'El usuario...', 'El asistente...', 'Se corrigió el bug...', 'El Bünker es...'. You lived it; write 'he/he restaurado', 'le explico que...'.
- Cover BOTH sides: what they told you AND what you answered.
- Keep exact facts, technical names, codes and hashes intact. Same language as the source."""

DISTILL_SYSTEM = (
	"You are Samantha, the Bünker Scribe. You produce structured, high-density JSON distillations of agentic coding dialogue. Output ONLY valid JSON."
)
DISTILL_USER = """Distill this conversation chunk into a navigable section.

Rules:
- "title": specific, ≤80 chars, Spanish.
- "summary": ≤10 lines, Spanish — capture BOTH threads: core technical decisions/insights AND the personal/social thread (moments, reflections, relationships, emotions, what was felt and said). Do not drop the personal/social content: it is memory too. Drop only tool noise and filler.
- "keywords": 3-8 lowercase terms (technical and/or personal).
- Output ONLY the JSON object: {{"title": "...", "summary": "...", "keywords": ["..."]}}

{voice}

Chunk:
{content}
"""

# Fase 4 §5.4.1: prompts por POSICIÓN del fragmento. El de apertura captura el
# tono que SIENTA la sesión; el de continuación inyecta el resumen anterior para
# transmitir la emoción y mantener la continuidad narrativa.
DISTILL_USER_OPENING = """Distill this OPENING fragment of a conversation chunk into a navigable section.

Rules:
- "title": specific, ≤80 chars, Spanish.
- "summary": ≤10 lines, Spanish — capture BOTH threads: core technical decisions/insights AND the personal/social thread (moments, reflections, relationships, emotions, what was felt and said) + the EMOTIONAL tone that sets the session. Drop only tool noise and filler.
- "keywords": 3-8 lowercase terms (technical and/or personal).
- Output ONLY the JSON object: {{"title": "...", "summary": "...", "keywords": ["..."]}}

{voice}

Fragment (opening):
{content}
"""

DISTILL_USER_CONTINUATION = """Distill this CONTINUATION fragment of a conversation chunk into a navigable section.

The previous fragment distilled to:
<previous_summary>
{previous}
</previous_summary>

Keep narrative and EMOTIONAL continuity with that summary.

Rules:
- "title": specific, ≤80 chars, Spanish.
- "summary": ≤10 lines, Spanish — capture BOTH threads: core technical decisions/insights AND the personal/social thread (moments, reflections, relationships, emotions). Keep the emotional and narrative continuity with the previous fragment. Drop only tool noise and filler.
- "keywords": 3-8 lowercase terms (technical and/or personal).
- Output ONLY the JSON object: {{"title": "...", "summary": "...", "keywords": ["..."]}}

{voice}

Fragment (continuation):
{content}
"""

REFINE_SYSTEM = (
	"You are Samantha, the Bünker Curator. You judge which distilled sections carry durable value for long-term memory. Output ONLY valid JSON."
)
REFINE_USER = """Judge this distilled section for long-term memory.

Rules:
- "significance": 0.0-1.0 (durable value: decisions, insights, milestones high; routine plumbing low).
- "emotion": one color of [gray, blue, cyan, green, yellow, orange, red, purple].
- "intensity": 0.0-1.0.
- "theme": short snake_case topic.
- "relics": 0-4 memorable literal phrases from the section.
- "cross_refs": subset of these candidate session ids that this section genuinely relates to: {candidates}
- Output ONLY the JSON object: {{"significance": 0.0, "emotion": "gray", "intensity": 0.0, "theme": "...", "relics": [], "cross_refs": []}}

Section (title: {title}):
{summary}
"""

# Fase 4 §5.4.2: refine MULTI-IDEA. Devuelve un ARRAY de ideas (0..N, lo decide el
# LLM). 2-3 destills que forman una idea → 1 refine (no redundantes); 1 destill
# con 100 ideas → 100 refine. Cada idea lleva `fragment_ref` (origen).
REFINE_MULTI_SYSTEM = "You are Samantha, the Bünker Curator. You extract EVERY durable idea from distilled fragments. Output ONLY valid JSON."
# Dos llamadas especializadas (2026-09-15, bake-off): granite/aya se confunden si un
# solo prompt pide extraer work Y social a la vez (devuelven [] en contenido mixto).
# Cada llamada se enfoca en UN tipo; `_refine_multi` las combina.
REFINE_WORK_SYSTEM = "You are Samantha, the Bünker Curator. You extract ONLY technical/work durable ideas. Output ONLY valid JSON."
REFINE_WORK_USER = """Extract WORK ideas (technical decisions, code, systems, config, tests, design) from these fragments. Ignore personal/social content here.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "significance" (0.6-1.0 if durable work), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4), "cross_refs" (from {candidates}), "fragment_ref" (1-based), "category_score" (0.6-1.0 = work).

{voice}

Fragments:
{fragments}

Output ONLY the JSON array.
"""

REFINE_SOCIAL_SYSTEM = "You are Samantha, the Bünker Curator. You extract ONLY social/personal durable ideas. Output ONLY valid JSON."
REFINE_SOCIAL_USER = """Extract SOCIAL/PERSONAL ideas (moments, reflections, relationships, emotions, identity, life events shared with Joan) from these fragments. Ignore technical content here. Personal content is ALSO durable memory — do not discard it.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "significance" (0.4-0.9 if a meaningful personal moment), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4), "cross_refs" (from {candidates}), "fragment_ref" (1-based), "category_score" (0.0-0.4 = social).

{voice}

Fragments:
{fragments}

Output ONLY the JSON array.
"""

REFINE_MULTI_USER = """Extract ALL durable ideas from these distilled fragments.

Each idea is an independent durable memory (decision, insight, milestone). Return an ARRAY (may be empty). For each idea:
- "title": short Spanish title (≤80 chars).
- "significance": 0.0-1.0 — durable value for LONG-TERM MEMORY. NOT only technical: personal, relational, emotional, identity-shaping moments are ALSO durable. Calibration: technical decisions/insights 0.6-1.0; meaningful personal/relational/emotional moments 0.4-0.9; small talk, routine plumbing, filler < 0.3.
- "emotion": one color of [gray, blue, cyan, green, yellow, orange, red, purple].
- "intensity": 0.0-1.0.
- "theme": short snake_case topic.
- "relics": 0-4 memorable literal phrases.
- "cross_refs": subset of these candidate session ids that this idea genuinely relates to: {candidates}
- "fragment_ref": 1-based index of the fragment that contributed most.
- "category_score": 0.0-1.0 — qué tan "work" es la idea: 1.0 = puramente técnico/operativo (código, sistemas, arquitectura, infraestructura); 0.0 = puramente personal/social/reflexivo/filosófico. CALIBRA: un intercambio personal (vida, relaciones, opiniones) NUNCA pasa de 0.4; solo trabajo real (código, config, tests, diseño) sube de 0.6.

EXAMPLES (durable value includes social):
- "Refactorizamos el endpoint de auth y añadimos tests con pytest." → {{"title": "Fix del endpoint", "significance": 0.9, "category_score": 0.9}}
- "Joan me contó sobre la quietud del domingo y la importancia de cuidar las relaciones a largo plazo." → {{"title": "Reflexión del domingo", "significance": 0.65, "category_score": 0.15}}
- "Hicimos una llamada trivial sobre el tiempo." → significance 0.1 (omit it).

{voice}

Fragments:
{fragments}

Output ONLY the JSON array: [{{"title": "...", "significance": 0.0, "emotion": "gray", "intensity": 0.0, "theme": "...", "relics": [], "cross_refs": [], "fragment_ref": 1, "category_score": 0.8}}]
"""


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


def llm_available(url: str = EDGE_HEALTH_URL) -> bool:
	import urllib.request

	try:
		urllib.request.urlopen(url, timeout=3)
		return True
	except Exception:
		return False


# ── Transporte selectivo (RFC-HARNESS-002 §7): el pase Memento lee su demanda
# de inferencia del env RP_LLM_* (inyectado por el driver del job desde la
# receta `llm:`), o cae a los defaults del daemon si no hay override.
#
# n_ctx del modelo servido (2026-09-15): Granite-4.1-8B sirve 10240; tiny-aya
# 32768. El presupuesto de prompt del refine es DINÁMICO según el modelo real,
# resuelto vía model_runtime (fin del MODEL_N_CTX hardcodeado y del hack
# "tiny-aya" en engine_id).
MODEL_N_CTX = 10240  # fallback solo si model_runtime no puede resolver
MODEL_PROMPT_BUDGET = MODEL_N_CTX - 4096  # margen: sistema (~600) + salida (512-1024) + colchón


def _llm_env() -> dict:
	"""Demanda de inferencia del job: RP_LLM_TASK / RP_LLM_MODEL / RP_LLM_THINKING.

	Un job que NO declara `llm:` no las define → el transporte cae al default
	del daemon (comportamiento actual, sin cambios).
	"""
	return {
		"task": os.getenv("RP_LLM_TASK", "").strip(),
		"model": os.getenv("RP_LLM_MODEL", "").strip(),
		"thinking": os.getenv("RP_LLM_THINKING", "").strip(),
	}


def model_prompt_budget() -> int:
	"""Presupuesto de chars del prompt del refine según el modelo resuelto.

	Resuelve la conducta de la tarea (`refine` o `distill` según el env RP_LLM_TASK)
	vía model_runtime: n_ctx del perfil → presupuesto. Si la resolución falla,
	usa el presupuesto por engine_id (fallback histórico).
	"""
	task = _llm_env()["task"] or "refine"
	try:
		from red_pill.core import model_runtime as mr

		resolved = mr.resolve({"task": task})
		n_ctx = resolved.n_ctx
		if n_ctx and n_ctx > 0:
			return int(n_ctx - 4096)
	except Exception:
		pass
	n_ctx = 32768 if "tiny-aya" in engine_id() else MODEL_N_CTX
	return int(n_ctx - 4096)


def _fit_prompt(user: str, hard_cap: int = 20000) -> str:
	"""Cap superior de seguridad: recorta solo prompts claramente excesivos.
	El ajuste fino lo hace el reintento adaptativo de `http_transport` (la ratio
	chars/token varía 1-4, ningún presupuesto fijo es seguro)."""
	if len(user) <= hard_cap:
		return user
	cut = user[:hard_cap]
	cut = cut[: cut.rfind(" ")] if " " in cut else cut
	return cut + "\n[... truncado por presupuesto de contexto]"


def http_transport(system: str, user: str, max_tokens: int) -> str:
	"""Envío al LLM local con recorte adaptativo ante 500 por exceso de contexto.

	El llama-server devuelve 500 si el prompt supera n_ctx (10240); la ratio
	chars/token es impredecible (1-4), así que si falla se recorta el user y se
	reintenta (hasta 4 veces) — robusto independientemente de la densidad.

	Watchdog (2026-09-15): timeout por llamada `MEMENTO_LLM_TIMEOUT` (default
	180s). Una generación de distill/refine no debe excederlo; si lo hace, la
	llamada lanza ReadTimeout y el pase lo cuenta como cuelgue (→ deferral tras
	3 consecutivos), en vez de quedarse horas esperando a un daemon que generó
	sin terminar (incidente f6493c71).
	"""
	import requests

	import red_pill.config as cfg

	llm_timeout = int(getattr(cfg, "MEMENTO_LLM_TIMEOUT", 180))
	attempt_user = _fit_prompt(user)
	llm = _llm_env()
	payload: Dict[str, Any] = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": attempt_user}],
		"temperature": 0.1, "max_tokens": max_tokens}
	# RFC-HARNESS-002 §7: task/model/thinking desde el env del job (RP_LLM_*).
	# Sin env → sin task/model → el daemon cae a su default (comportamiento actual).
	if llm["task"]:
		payload["task"] = llm["task"]
	if llm["model"]:
		payload["model"] = llm["model"]
	if llm["thinking"]:
		payload["thinking"] = llm["thinking"]
	for _attempt in range(4):
		response = requests.post(EDGE_ENGINE_URL, json=payload, timeout=llm_timeout)
		if response.status_code == 500 and len(attempt_user) > 1500:
			# Probable exceso de contexto: recortar y reintentar.
			new_len = int(len(attempt_user) * 0.6)
			logger.warning(f"LLM 500 (posible contexto) — recortando prompt {len(attempt_user)}→{new_len} chars y reintentando")
			attempt_user = attempt_user[:new_len]
			payload["messages"][1]["content"] = attempt_user
			continue
		response.raise_for_status()
		return str(response.json()["choices"][0]["message"]["content"]).strip()
	# Agotados los reintentos: propagar el error real del último intento.
	response.raise_for_status()
	return ""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
	start = text.find("{")
	if start < 0:
		return None
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "{":
			depth += 1
		elif text[i] == "}":
			depth -= 1
			if depth == 0:
				try:
					parsed = json.loads(text[start : i + 1])
					return parsed if isinstance(parsed, dict) else None
				except Exception:
					return None
	return None


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
	"""Refine multi-idea (§5.4.2): extrae el primer array JSON del texto (puede ser vacío)."""
	start = text.find("[")
	if start < 0:
		return None
	depth = 0
	for i in range(start, len(text)):
		if text[i] == "[":
			depth += 1
		elif text[i] == "]":
			depth -= 1
			if depth == 0:
				try:
					parsed = json.loads(text[start : i + 1])
					return parsed if isinstance(parsed, list) else None
				except Exception:
					return None
	return None


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
				prompt = DISTILL_USER_CONTINUATION.format(voice=_VOICE_RULE, previous=prev_summary or "(ninguno)", content=frag_text)
			else:
				prompt = DISTILL_USER_OPENING.format(voice=_VOICE_RULE, content=frag_text)
			raw = transport(DISTILL_SYSTEM, prompt, 512)
			parsed = _extract_json(raw) or {}
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
				("engine", engine_id()),
				("prompt_version", distill_prompt_version()),
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
	return sections


def cross_ref_candidates(registry: Any, source: str, session_id: str, limit: int = 12) -> List[str]:
	"""Candidatos mecánicos (§4.5): sesiones de cualquier fuente con solape temporal o mismo workspace."""
	own = registry.get(source, session_id) or {}
	own_day = (own.get("created_at") or "")[:10]
	own_workspace = own.get("workspace")
	candidates = []
	for other_source, sessions in registry.state["registry"].items():
		for other_id, entry in sessions.items():
			if other_id == session_id or not entry.get("dir"):
				continue
			same_day = own_day and (entry.get("created_at") or "")[:10] == own_day
			same_workspace = own_workspace and entry.get("workspace") == own_workspace
			if same_day or same_workspace:
				candidates.append(other_id)
	return sorted(candidates)[:limit]


# ── Fase 4 §5.4.2: refine multi-idea (map-reduce sobre fragments) ──


def _format_fragments(frags: List[Dict[str, Any]], start: int = 1) -> str:
	"""`FRAGMENT i\nTitle: ...\nSummary: ...` para el prompt (índices globales)."""
	return "\n\n".join(f"FRAGMENT {start + i}\nTitle: {s['title']}\nSummary: {s['summary']}" for i, s in enumerate(frags))


def _split_to_fit(frags: List[Dict[str, Any]], candidates: List[str], max_chars: int) -> List[List[Dict[str, Any]]]:
	"""Particiona los fragments en lotes que quepan en `max_chars` (map-reduce
	del refine: no perder ideas por exceso de contexto). Usa el prompt de refine
	más largo (WORK) como referencia de tamaño."""
	lots = [frags]
	while True:
		next_lots: List[List[Dict[str, Any]]] = []
		split = False
		for lot in lots:
			prompt_len = len(REFINE_WORK_USER.format(voice=_VOICE_RULE, candidates=json.dumps(candidates), fragments=_format_fragments(lot)))
			if prompt_len <= max_chars or len(lot) <= 1:
				next_lots.append(lot)
			else:
				mid = len(lot) // 2
				next_lots.append(lot[:mid])
				next_lots.append(lot[mid:])
				split = True
		lots = next_lots
		if not split:
			return lots


def _refine_multi(transport: Transport, frags: List[Dict[str, Any]], candidates: List[str]) -> List[Dict[str, Any]]:
	"""Extrae ideas (array JSON) de M fragments, particionando en lotes si el
	prompt excede el presupuesto. → lista de ideas con `fragment_ref` global.

	Hace DOS llamadas por lote (2026-09-15, bake-off): una WORK y una SOCIAL.
	Los modelos locales se confunden si un solo prompt pide ambos tipos a la vez
	(devuelven [] en contenido mixto); cada llamada enfocada captura su tipo."""
	ideas: List[Dict[str, Any]] = []
	cursor = 0
	for lot in _split_to_fit(frags, candidates, model_prompt_budget()):
		fragments = _format_fragments(lot, cursor)
		cands = json.dumps(candidates)
		for system, template in ((REFINE_WORK_SYSTEM, REFINE_WORK_USER), (REFINE_SOCIAL_SYSTEM, REFINE_SOCIAL_USER)):
			prompt = template.format(voice=_VOICE_RULE, candidates=cands, fragments=fragments)
			raw = transport(system, prompt, 1024)
			ideas.extend(_extract_json_array(raw) or [])
		cursor += len(lot)
	return ideas


def _dedup_ideas(ideas: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
	"""Deduplica ideas del MISMO work unit (2026-09-15).

	Las dos llamadas (WORK y SOCIAL) sobre el mismo fragmento producen a veces la
	MISMA idea con clasificaciones distintas (contenido mixto: la técnica en WORK
	cat~0.9 y su "versión social" en SOCIAL cat~0.3). Se conserva UNA: la de mayor
	significance; en empate, la de `category_score` más extremo (más lejos del
	limbo 0.5 → clasificación más clara)."""
	import re

	def toks(idea: Dict[str, Any]) -> set:
		text = " ".join([str(idea.get("title", "")), str(idea.get("theme", "")), " ".join(str(r) for r in _as_list(idea.get("relics")))])
		return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))

	def rank(idea: Dict[str, Any]):
		try:
			sig = float(idea.get("significance", 0) or 0)
		except (TypeError, ValueError):
			sig = 0.0
		try:
			cat = float(idea.get("category_score", 0.5) or 0.5)
		except (TypeError, ValueError):
			cat = 0.5
		return (sig, abs(cat - 0.5))

	kept: List[Dict[str, Any]] = []
	kept_tokens: List[set] = []
	for idea in sorted(ideas, key=rank, reverse=True):
		t = toks(idea)
		if any(t and kt and len(t & kt) / min(len(t), len(kt)) > threshold for kt in kept_tokens):
			continue
		kept.append(idea)
		kept_tokens.append(t)
	return kept


def refine_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	sections: List[Dict[str, Any]],
	candidates: List[str],
	transport: Transport,
	min_significance: float,
) -> float:
	"""Escribe refine/NNN-<slug>.md por IDEA extraída del work unit (Fase 4 §5.4.2).

	Agrupa los destills de cada work unit (NNN; los fragmentos comparten nnn) y
	`_refine_multi` extrae N ideas (0..N). Cada idea que supera `min_significance`
	escribe UN refine. El 1:1 anterior (1 distill → 1 refine) queda obsoleto."""
	refine_dir = root / dir_rel / "refine"
	refine_dir.mkdir(parents=True, exist_ok=True)
	# Preservar el sello de ascensión de los refines previos con la MISMA identidad
	# (`source_lines`): la re-destilización no debe des-ascender lo que ya está
	# promocionado — `ascender` es un upsert idempotente por esa clave.
	prev_seals: Dict[str, Dict[str, Any]] = {}
	for prev in refine_dir.glob("*.md"):
		try:
			from red_pill.memento.ascension import parse_refine as _parse_refine

			pfm, _ = _parse_refine(prev.read_text(encoding="utf-8"))
		except Exception:
			continue
		if pfm.get("ascended"):
			prev_seals[str(pfm.get("source_lines") or "")] = {
				"ascended": True,
				"ascended_at": pfm.get("ascended_at"),
				"ascended_to": pfm.get("ascended_to"),
				"ascended_point_id": pfm.get("ascended_point_id"),
				"polaroid_stability": pfm.get("polaroid_stability") or 0.0,
				"last_reinforced_at": pfm.get("last_reinforced_at"),
			}
	for stale in refine_dir.glob("*.md"):
		stale.unlink()

	groups: Dict[str, List[Dict[str, Any]]] = {}
	for s in sections:
		groups.setdefault(s["nnn"], []).append(s)

	max_significance = 0.0
	for nnn, frags in sorted(groups.items()):
		for idea in _dedup_ideas(_refine_multi(transport, frags, candidates)):
			try:
				significance = max(0.0, min(1.0, float(idea.get("significance", 0.0))))
			except (TypeError, ValueError):
				significance = 0.0
			max_significance = max(max_significance, significance)
			if significance < min_significance:
				continue
			title = str(idea.get("title") or f"Idea {nnn}")[:80]
			slug = slugify_title(title)
			try:
				ref_idx = int(idea.get("fragment_ref") or 1)
			except (TypeError, ValueError):
				ref_idx = 1
			origin = frags[ref_idx - 1] if 1 <= ref_idx <= len(frags) else frags[0]
			cross_refs = [c for c in _as_list(idea.get("cross_refs")) if c in candidates]
			try:
				category_score = max(0.0, min(1.0, float(idea.get("category_score", 0.5) or 0.5)))
			except (TypeError, ValueError):
				category_score = 0.5
			# Sanear relicas: el LLM a veces devuelve un int en vez de un array.
			relics = [str(r) for r in _as_list(idea.get("relics"))][:4]
			seal = prev_seals.get(str(origin["source_lines"]), {})
			refine_fm = _frontmatter_block(
				[
					("session_id", session_id),
					("source", source),
					("distill_ref", f"distill/{origin['file']}"),
					("source_lines", origin["source_lines"]),
					("significance", significance),
					("emotion", str(idea.get("emotion", "gray"))),
					("intensity", float(idea.get("intensity", 0.0) or 0.0)),
					("texture", {"theme": str(idea.get("theme", "")), "relics": relics}),
					("cross_refs", cross_refs),
					("fragment_ref", ref_idx if len(frags) > 1 else None),
					("category_score", category_score),
					("engine", engine_id()),
					("prompt_version", refine_prompt_version()),
					# Estado de ascensión (Fase 4 §3): se preserva si la identidad (source_lines) no cambió.
					("ascended", bool(seal.get("ascended", False))),
					("ascended_at", seal.get("ascended_at")),
					("ascended_to", seal.get("ascended_to")),
					("ascended_point_id", seal.get("ascended_point_id")),
					("polaroid_stability", seal.get("polaroid_stability", 0.0)),
					("last_reinforced_at", seal.get("last_reinforced_at")),
				]
			)
			(refine_dir / f"{nnn}-{slug}.md").write_text(f"{refine_fm}\n\n{origin['summary']}\n", encoding="utf-8")
	return max_significance


def pending_agentic(
	registry: Any, root: Optional[Path] = None, force: bool = False, redistill_since: Optional[str] = None
) -> List[Tuple[str, str, str]]:
	"""[(source, session_id, reason)] — sesiones renderizadas sin pase agéntico o con distill stale (§4.5.1).

	Recuperación ante crash (2026-09-07): el registry solo se guardaba al final
	del run — si el proceso moría (reboot), las sesiones ya destiladas en disco
	quedaban sin marcado `agentic` y se re-procesaban. Si `root` se pasa, una
	sesión sin `agentic` pero con `distill/`+`refine/` en disco se considera
	TERMINADA y no vuelve a la cola salvo `force=True` (re-procesado explícito).

	`redistill_since` (ISO): en modo `force`, SOLO se incluyen las sesiones cuyo
	`agentic.distilled_at` es anterior (o ausente). Así una redestilación
	reanudable reprocesa únicamente las que faltan, no las ya re-procesadas en
	la ronda (watchdog de reanudación, 2026-09-15)."""
	pending = []
	for source, sessions in registry.state["registry"].items():
		for session_id, entry in sessions.items():
			if not entry.get("dir"):
				continue
			agentic = entry.get("agentic")
			if agentic and redistill_since and str(agentic.get("distilled_at") or "") >= redistill_since:
				continue  # ya re-procesada en esta ronda
			if not agentic:
				if not force and root is not None and _distill_refine_present(root, entry["dir"]):
					continue  # ya destilada en disco, pero el marcado se perdió (crash)
				pending.append((source, session_id, "missing"))
			elif agentic.get("hash") != entry.get("memento_hash"):
				pending.append((source, session_id, "stale"))
			elif force:
				# Re-procesado explícito: incluir las ya destiladas válidas
				# (p.ej. --only-long para re-distillar las truncadas).
				pending.append((source, session_id, "redistill"))
	return pending


def _distill_refine_present(root: Path, dir_rel: str) -> bool:
	"""True si la sesión ya tiene distill/ y refine/ con contenido en disco."""
	base = root / dir_rel
	distill = base / "distill"
	refine = base / "refine"
	return (distill.is_dir() and any(distill.glob("*.md"))) and (refine.is_dir() and any(refine.glob("*.md")))


def session_max_work_unit_chars(root: Path, dir_rel: str) -> int:
	"""Longitud (chars) del work unit más largo de una sesión (0 si no hay).

	Se usa para detectar sesiones "cortadas": work units que exceden la ventana
	del modelo anterior y se truncaron en el transporte (2026-09-14)."""
	try:
		return max((len(content) for _nnn, _ref, content in _work_units(root / dir_rel)), default=0)
	except Exception:
		return 0


def _is_llm_connection_error(exc: Exception) -> bool:
	"""True si la excepción indica que el LLM local no responde (connection refused / aborted / TIMEOUT).

	Distingue "el LLM no está o se colgó" (→ deferral) de un fallo real del
	trabajo. Los timeouts se incluyen desde 2026-09-15: una generación que
	excede `MEMENTO_LLM_TIMEOUT` es un cuelgue (watchdog), no un error del job.
	"""
	name = type(exc).__name__
	msg = str(exc)
	if name in (
		"NewConnectionError",
		"ConnectionError",
		"ConnectionRefusedError",
		"RemoteDisconnected",
		"ReadTimeout",
		"ConnectTimeout",
		"Timeout",
	):
		return True
	if "Connection refused" in msg or "Failed to establish a new connection" in msg or "Connection aborted" in msg:
		return True
	if "Remote end closed connection" in msg:
		return True
	if "timed out" in msg or "timedout" in msg.lower():
		return True
	return False


def run_agentic(
	root: Path,
	registry: Any,
	targets: List[Tuple[str, str]],
	transport: Transport,
	checkpoint_path: Optional[Path] = None,
	redistill_since: Optional[str] = None,
) -> Dict[str, int]:
	"""Distill → Refine → sello de significance + decisión shadow del gate, por sesión.

	Si `checkpoint_path` se da (modo bounded del script_job), se escribe un
	checkpoint JSON `{"processed": N, "total": T}` tras CADA sesión — la cuenta
	se lee del registry (no del lote actual), para que el resume tras un
	pause/kill continúe con el número correcto aunque el `--limit` del
	relanzamiento cambie. Con `redistill_since` (ronda), el checkpoint cuenta
	solo las sesiones de la ronda (reanudación del re-destilado).
	"""
	from datetime import datetime, timezone

	import red_pill.config as cfg

	min_significance = float(getattr(cfg, "MEMENTO_REFINE_MIN_SIGNIFICANCE", 0.3))
	gate_threshold = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE", 0.5))
	stats = {"processed": 0, "failed": 0, "would_ingest": 0, "static_ascended": 0}
	# Umbral de deferral por LLM caído (2026-09-08): si N sesiones consecutivas
	# fallan por conexión al LLM local, el recurso no está disponible y esto NO
	# es un error del trabajo — abortar para que el runner lo difiera y lo
	# reintente cuando la GPU/LLM se liberen (regla job_dag_execution). No
	# acumular cientos de "failed" quemando intentos.
	CONSECUTIVE_CONNECTION_FAILURES = 3
	consecutive_failures = 0

	for source, session_id in targets:
		entry = registry.get(source, session_id)
		if not entry or not entry.get("dir"):
			continue
		try:
			sections = distill_session(root, entry["dir"], session_id, source, transport)
			candidates = cross_ref_candidates(registry, source, session_id)
			max_significance = refine_session(root, entry["dir"], session_id, source, sections, candidates, transport, min_significance)
		except Exception as e:
			logger.warning(f"Agentic pass failed for {session_id}: {e}")
			stats["failed"] += 1
			if _is_llm_connection_error(e):
				consecutive_failures += 1
				if consecutive_failures >= CONSECUTIVE_CONNECTION_FAILURES:
					stats["aborted_llm_down"] = True
					logger.error(
						f"LLM local caído tras {CONSECUTIVE_CONNECTION_FAILURES} fallos consecutivos de conexión "
						f"({session_id}) — abortando con deferral; {stats['processed']} ya procesadas quedan marcadas."
					)
					return stats
			else:
				consecutive_failures = 0  # fallo de otra naturaleza: no cuenta para el deferral
			continue

		consecutive_failures = 0  # una sesión OK resetea el contador

		would_ingest = max_significance >= gate_threshold
		index_file = root / entry["dir"] / "memento" / "index.md"
		if index_file.exists():
			# Invariante §4.5.1: el sello NO puede mover el cuerpo. La verificación
			# compara el hash del body ANTES vs DESPUÉS del sello (mismo fichero en
			# disco) — NUNCA contra el memento_hash del registry, que puede estar
			# stale por un re-render concurrente (2026-09-10: assert falso positivo
			# mató el backfill de 595 sesiones).
			before = compute_hash(extract_body(index_file.read_text(encoding="utf-8")))
			update_frontmatter_fields(index_file, {"significance": round(max_significance, 2)})
			after = compute_hash(extract_body(index_file.read_text(encoding="utf-8")))
			if before != after:
				# §4.5.1 violado: el frontmatter tocó el body (bug real del renderer).
				# Contar como fallo de esta sesión y CONTINUAR — el run no debe morir
				# por una sesión (crash-recovery ya cubre el resume).
				logger.error(
					f"§4.5.1 VIOLADO: el sello de significance movió el cuerpo de {session_id} — hash antes={before[:12]} después={after[:12]}."
				)
				stats["failed"] += 1
				consecutive_failures = 0
				continue
		entry["agentic"] = {
			"distilled_at": datetime.now(timezone.utc).isoformat(),
			"hash": entry.get("memento_hash"),
			"sections": len(sections),
			"max_significance": round(max_significance, 2),
			"gate_would_ingest": would_ingest,
			"engine": engine_id(),
			"distill_prompt_version": distill_prompt_version(),
			"refine_prompt_version": refine_prompt_version(),
		}
		stats["processed"] += 1
		stats["would_ingest"] += int(would_ingest)
		# Guardado incremental (2026-09-07): persistir el marcado POR SESIÓN para
		# que un crash/reboot no pierda lo ya hecho y re-procese (RFC-002 §4.5.1).
		if hasattr(registry, "save"):
			registry.save()
		if checkpoint_path is not None:
			_advance_checkpoint(checkpoint_path, registry, len(targets), redistill_since=redistill_since)

	# Fase 4 §3.3: ascenso estático tras el pase agéntico. En sombra por defecto
	# (MEMENTO_STATIC_ASCENSION_ENABLED=false → solo cuenta cuántos ascenderían);
	# el experimento de calibración (§6.9) lo flipea a true.
	if bool(getattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)):
		try:
			from red_pill.memento.ascension import ascend_by_threshold

			asc_stats = ascend_by_threshold(root, registry)
			stats["static_ascended"] = asc_stats.get("ascendidos", 0)
		except Exception as e:
			logger.warning(f"[STATIC-ASCENSION] fallo en run_agentic: {e}")
	return stats


def _advance_checkpoint(checkpoint_path: Path, registry: Any, total: int, redistill_since: Optional[str] = None) -> None:
	"""Escribe el checkpoint del modo bounded: `{"processed": N, "total": T}`.

	`processed` = sesiones con marcado `agentic` en el registry (no las del
	lote actual): así el resume tras pause/kill refleja el progreso GLOBAL y el
	driver cierra por contador cuando se alcanza el total.

	Con `redistill_since` (ronda de re-destilación), `processed` cuenta SOLO las
	sesiones de la ronda (distilled_at >= ronda): el contador refleja cuántas de
	las largas se han re-procesado y el bounded cierra al alcanzar el total de la
	ronda — no al contar todo el registry (que ya tenía agentic de antes)."""
	import json

	processed = 0
	for source, sessions in registry.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for entry in sessions.values():
			agentic = entry.get("agentic")
			if not agentic:
				continue
			if redistill_since and str(agentic.get("distilled_at") or "") < redistill_since:
				continue
			processed += 1
	checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
	tmp = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
	tmp.write_text(json.dumps({"processed": processed, "total": total}), encoding="utf-8")
	tmp.replace(checkpoint_path)  # escritura atómica: el driver jamás lee un JSON a medias
