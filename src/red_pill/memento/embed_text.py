"""Texto que se embebe para un engrama curado de Memento (feedback de recall 2026-09-25).

El vector de un engrama se calculaba sobre el cuerpo de la nota tal cual. Medido
tras la resiembra:

- Solo el 28,8% de las notas nombra el proyecto/herramienta: la entidad que ancla
la idea vive en el contexto de la sesión, no en la nota (la nota de una revisión
contractual no nombra a la empresa ni el asunto → coseno 0,17 contra su consulta).
- El 50,2% abre con la muletilla "Joan me dijo/explicó/pidió…": el embedder trunca
a 128 tokens y pondera el arranque, así que media colección comparte los primeros
tokens y los vectores se parecen más de lo que deberían.
- Fuga de la Bio de identidad ("el operador catalán", "narradora del Búnker").

`engram_embed_text` compone el texto a embeber: `tema · reliquias · cuerpo sin
muletilla ni fuga`. **Solo cambia lo que se embebe**: el `content` que se guarda y
se muestra queda intacto. Determinista (sin LLM). Gobernado por
`MEMENTO_EMBED_ENRICHED` (RULE 4, default OFF); con OFF devuelve el cuerpo tal cual.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

# Muletilla de apertura: "Joan me dijo que…", "Le expliqué a Joan que…", "Joan me pide…".
_VERBS = (
	r"dijo|dice|explicó|explica|pidió|pide|comentó|comenta|contó|cuenta|preguntó|pregunta|confirmó|confirma|"
	r"indicó|indica|informó|informa|propuso|propone|mostró|muestra|recordó|recuerda|sugirió|sugiere|planteó|plantea|"
	r"expliqué|explico|dije|digo|conté|comenté|propuse|confirmé|indiqué|informé|recordé|sugerí|planteé|pregunté|respondí"
)
_LEAD_RE = re.compile(
	rf"^\s*(?:(?:Joan|Aleth|Él|Ella)\s+)?(?:me|le|les|nos)\s+(?:{_VERBS})(?:\s+a\s+(?:Joan|Aleth))?\s*(?:,\s*)?(?:que\s+)?",
	re.IGNORECASE,
)
# Fuga de la Bio de identidad dentro del cuerpo (aposiciones que no aportan hecho).
_BIO_RE = re.compile(
	r",?\s*(?:el\s+operador(?:\s+ingeniero)?\s+catal[aá]n|yo,\s*Aleth,\s*narrador[a]?\s+del\s+B[uú]nker|"
	r"Aleth,\s*narrador[a]?\s+del\s+B[uú]nker|narrador[a]?\s+del\s+B[uú]nker)\s*,?",
	re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


def strip_lead(text: str) -> str:
	"""Quita la muletilla de apertura y las aposiciones de la Bio; capitaliza."""
	body = _BIO_RE.sub(" ", str(text or ""))
	body = _LEAD_RE.sub("", body, count=1)
	body = _WS_RE.sub(" ", body).strip(" ,;")
	return body[:1].upper() + body[1:] if body else ""


def _readable_theme(theme: Any) -> str:
	return _WS_RE.sub(" ", str(theme or "").replace("_", " ").replace("-", " ")).strip()


def engram_embed_text(text: str, theme: Any = None, relics: Optional[Iterable[Any]] = None) -> str:
	"""`tema · reliquias · cuerpo` — el ancla de entidad delante (el embedder trunca)."""
	parts = []
	readable = _readable_theme(theme)
	if readable:
		parts.append(readable)
	relic_list = [str(r).strip() for r in (relics or []) if str(r).strip()][:4]
	if relic_list:
		parts.append(", ".join(relic_list))
	body = strip_lead(text) or str(text or "").strip()
	parts.append(body)
	return " · ".join(parts)


def enriched_enabled() -> bool:
	import red_pill.config as cfg

	return bool(getattr(cfg, "MEMENTO_EMBED_ENRICHED", False))


def embedding_text_for(text: str, payload: Optional[Dict[str, Any]]) -> str:
	"""Punto único: qué texto se embebe para un punto con este payload.

	Engramas de Memento (`node_type: memento_engram`) con el flag ON → texto
	enriquecido; cualquier otro punto, o flag OFF → el texto tal cual. Lo usan la
	escritura (`MemoryManager.add_memory`), la re-vectorización del soul kit y
	`scripts/qdrant_reembed.py --text-mode enriched`, para que un re-embebido nunca
	devuelva un engrama al texto plano por accidente.
	"""
	payload = payload or {}
	if payload.get("node_type") != "memento_engram" or not enriched_enabled():
		return text
	return engram_embed_text(text, payload.get("theme"), payload.get("relics"))
