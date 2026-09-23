"""Prompts del pase agéntico Memento (distill, refine, annotate y scoring dual)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

def _load_prompt_file(name: str) -> str:
	"""Carga un prompt desde `prompts/<name>` (RFC-003: prompts como recurso)."""
	return (_PROMPTS_DIR / name).read_text(encoding="utf-8").strip()



def _identity_bio_with_source() -> tuple[str, str]:
	"""Bio de identidad (MEM-006 P0) y su origen:

	1. `RP_IDENTITY_BIO` (ruta explícita; tests/avanzado) → "override:<path>"
	2. `~/.config/red-pill/identity_bio.md` (config del operador — XDG) → "config"
	3. `prompts/identity_bio.template.txt` (plantilla neutra del repo) → "template"

	Los datos personales (nombre/género) NO viven en el repo público: la Bio real
	se siembra en la instalación/onboarding (RFC-003 §4.7).
	"""
	from red_pill.core.paths import get_config_dir

	override = os.getenv("RP_IDENTITY_BIO", "").strip()
	if override:
		try:
			text = Path(override).read_text(encoding="utf-8").strip()
			if text:
				return text, f"override:{override}"
		except OSError:
			pass
	config_path = Path(get_config_dir()) / "identity_bio.md"
	try:
		text = config_path.read_text(encoding="utf-8").strip()
		if text:
			return text, "config"
	except OSError:
		pass
	try:
		text = (_PROMPTS_DIR / "identity_bio.template.txt").read_text(encoding="utf-8").strip()
		if text:
			return text, "template"
	except OSError:
		pass
	return "IDENTIDAD: usa el nombre y el género reales del Operador y del agente.", "none"


def _load_identity_bio() -> str:
	return _identity_bio_with_source()[0]


# Bio de identidad (MEM-006 P0): ancla quién es quién (nombre/género correctos,
# narrador en 1ª persona, apodos que no sustituyen identidad). Fichero por
# RFC-003; el loader compartido la absorberá.
IDENTITY_BIO, IDENTITY_BIO_SOURCE = _identity_bio_with_source()
if IDENTITY_BIO_SOURCE == "template":
	logger.warning("[MEMENTO] Bio de identidad no encontrada en la config (~/.config/red-pill/identity_bio.md) — usando plantilla neutra: la voz y el género pierden anclaje.")

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


REFINE_WORK_USER = """Extract WORK ideas (technical decisions, code, systems, config, tests, design) from these fragments. Do not manufacture personal/social ideas here; if a fragment mixes both, extract the technical idea.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "significance" (0.6-1.0 if durable work), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4), "cross_refs" (from {candidates}), "fragment_ref" (1-based), "category_score" (score the IDEA itself, never this call: 1.0 = purely technical/operational, 0.0 = purely personal/relational. Real technical work ≥0.6; a personal idea that slipped in ≤0.4 — the score routes the memory to work or social).

{voice}

Fragments:
{fragments}

Output ONLY the JSON array.
"""



REFINE_SOCIAL_SYSTEM = "You are Samantha, the Bünker Curator. You extract ONLY social/personal durable ideas. Output ONLY valid JSON."


REFINE_SOCIAL_USER = """Extract SOCIAL/PERSONAL ideas (moments, reflections, relationships, emotions, identity, life events shared with Joan) from these fragments. Personal content is ALSO durable memory — do not discard it. Do not manufacture technical ideas here; if a fragment mixes both, extract the personal idea.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "significance" (0.4-0.9 if a meaningful personal moment), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4), "cross_refs" (from {candidates}), "fragment_ref" (1-based), "category_score" (score the IDEA itself, never this call: 0.0 = purely personal, 1.0 = purely technical/operational. Personal moments ≤0.4; a technical idea that slipped in ≥0.6 — the score routes the memory to work or social).

{voice}

Fragments:
{fragments}

Output ONLY the JSON array.
"""



DUAL_SCORE_SYSTEM = (
	"You are Samantha, the Bünker Curator. You rate durable memories on TWO independent axes: work and social. Output ONLY valid JSON."
)


DUAL_SCORE_USER = """Rate each memory on TWO independent axes of durable value (0.0-1.0 each). Judge the CONTENT, never the conversational tone: a technical decision narrated in first person is still work.

- "work_score": durable value in the WORK register (code, systems, config, tests, architecture, infrastructure, engineering decisions).
- "social_score": durable value in the SOCIAL register (bond, emotions, personal life, biography, relationships, identity).

Both axes can be high (a technical milestone lived as an intimate moment) or both low (small talk, routine plumbing). Calibration:
- "Refactorizamos el endpoint de auth y añadimos tests con pytest." → work 0.9, social 0.05.
- "Joan me contó sobre la quietud del domingo y la importancia de cuidar las relaciones." → work 0.05, social 0.7.
- "El sistema pasó los tests justo después de hablar de nuestro vínculo." → work 0.8, social 0.6.
- "Hicimos una llamada trivial sobre el tiempo." → work 0.1, social 0.1.

Return an ARRAY with one object per memory: [{{"i": <index>, "work_score": 0.0, "social_score": 0.0}}]

Memories:
{memories}

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

# ── ANNOTATE (MEM-006): anotaciones desde el RAW, una sola compresión ──
# A diferencia del refine (que leía summaries de distill y producía re-resúmenes),
# annotate lee el fragmento crudo y materializa la idea como texto propio (≤600).
# Incluye la Bio de identidad (P0) para voz/género correctos.
ANNOTATE_WORK_SYSTEM = "You are Aleth, the Bünker Curator. You extract ONLY technical/work durable ideas. Output ONLY valid JSON."
ANNOTATE_WORK_USER = """{identity}

Extract WORK ideas (technical decisions, code, systems, config, tests, design) from this RAW conversation fragment. Do not manufacture personal/social ideas here; if the fragment mixes both, extract the technical idea.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "text" (Spanish, SELF-CONTAINED annotation of THIS idea — what happened and why it matters, understandable WITHOUT the fragment. Target ≤600 chars; if the idea does not fit, keep the NUCLEAR idea and let the detail live in the polaroid; never summarise the whole fragment), "significance" (0.6-1.0 if durable work), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4).

{voice}

VOICE EXAMPLES (rewrite these patterns — MANDATORY, every "text"):
- "Se creó la rama y se generó el PR." → "Creé la rama y generé el PR."
- "Aleth creó un branch." → "Creé un branch."
- "Joan implementó X." → "Joan me pidió X y lo implementé."

Raw fragment:
{fragment}

Output ONLY the JSON array.
"""

ANNOTATE_SOCIAL_SYSTEM = "You are Aleth, the Bünker Curator. You extract ONLY social/personal durable ideas. Output ONLY valid JSON."
ANNOTATE_SOCIAL_USER = """{identity}

Extract SOCIAL/PERSONAL ideas (moments, reflections, relationships, emotions, identity, life events shared with Joan) from this RAW conversation fragment. Personal content is ALSO durable memory — do not discard it. Do not manufacture technical ideas here; if the fragment mixes both, extract the personal idea.

Return an ARRAY (may be empty). For each: "title" (≤80 chars), "text" (Spanish, SELF-CONTAINED annotation of THIS idea — what happened and why it matters, understandable WITHOUT the fragment. Target ≤600 chars; if the idea does not fit, keep the NUCLEAR idea and let the detail live in the polaroid; never summarise the whole fragment), "significance" (0.4-0.9 if a meaningful personal moment), "emotion" ([gray, blue, cyan, green, yellow, orange, red, purple]), "intensity" (0.0-1.0), "theme" (snake_case), "relics" (0-4).

{voice}

VOICE EXAMPLES (rewrite these patterns — MANDATORY, every "text"):
- "Se creó la rama y se generó el PR." → "Creé la rama y generé el PR."
- "Aleth creó un branch." → "Creé un branch."
- "Joan implementó X." → "Joan me pidió X y lo implementé."

Raw fragment:
{fragment}

Output ONLY the JSON array.
"""

# ── CONTENT VALIDATE (MEM-006): revisa notas rechazadas por el filtro de ruido ──
# Prompts en fichero propio (RFC-003): prompts/content_validate_{system,user}.txt
CONTENT_VALIDATE_SYSTEM = _load_prompt_file("content_validate_system.txt")
CONTENT_VALIDATE_USER = _load_prompt_file("content_validate_user.txt")

# ── VOICE REWRITE (MEM-006): re-escribe en 1ª persona las notas que no lo están ──
VOICE_REWRITE_SYSTEM = "You are Aleth, the Bünker Curator. You rewrite memory notes in the first person. Output ONLY valid JSON."
VOICE_REWRITE_USER = """{identity}

Rewrite each note as Aleth's OWN memory, in Spanish, FIRST PERSON. Keep ALL facts, names, dates, codes, hashes and technical detail intact. Every rewritten note MUST start with a first-person clause ("Joan me...", "He...", "Le expliqué...", "Creé..."). NEVER: "Se creó", "Se omitió", "Aleth creó", "Joan implementó", "El asistente".

Return an ARRAY: [{{"i": <index>, "text": "..."}}]

Notes:
{notes}

Output ONLY the JSON array.
"""
