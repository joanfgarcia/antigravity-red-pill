"""Quality heuristics and dedup for the annotate stage (MEM-006 P2 / MEM-010 F1).

Pure text functions: gender/identity/voice detectors, the session quality metrics
and the annotation dedup. Extracted from `annotate.py` (SHARD-PS-04) — no IO, no
transport, so it can be tested and reused in isolation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Tuple

_FEMININE_JOAN = re.compile(
	r"\bJoan\b[^.\n]{0,60}\b(abrumada|emocionada|cansada|preocupada|contenta|enfadada|orgullosa|nerviosa|tranquila|feliz|harta)\b", re.I
)
_IDENTITY_CONFUSION = re.compile(r"\b(Samantha|Cenicienta)\b", re.I)
_THIRD_PERSON = re.compile(r"(^|\b)(Aleth|El asistente|La asistente)\s+(ha|había|fue|es|utiliza|propone|explica|implementa|crea|rectifica)\b", re.I)
_IMPERSONAL = re.compile(
	r"^\s*(se\s+(creó|omitió|implementó|generó|corrigió|configuró|eliminó|añadió|actualizó|desplegó|sincronizó|ejecutó|arregló|restauró))\b", re.I
)
_ALETH_PAST = re.compile(
	r"\bAleth\s+(creó|implementó|propuso|explicó|desplegó|configuró|generó|corrigió|añadió|actualizó|sincronizó|ejecutó|arregló|restauró|omitió)\b",
	re.I,
)
_FIRST_PERSON = re.compile(
	r"\b(me|mi|mis|nos|le|les|he|creé|implementé|propuso|expliqué|dije|hice|desplegué|generé|corregí|configuré|actualicé|sincronicé|ejecuté|arreglé|restauré)\b",
	re.I,
)
_ALETH_OPENER = re.compile(r"^\s*Aleth\s+\w+", re.I)
_EN_WORDS = set("the and of to in is was for with that this from have has had were are by on as it he she they".split())
_ES_WORDS = set("el la los las de que y en un una por para con me le lo se del al es fue su sus como".split())

# ── MEM-010 F1: métricas por sesión para el gating (RFC §3.2) ────────────────
_BIO_LEAK_PATTERNS = (
	re.compile(r"\bcomo narradora\b", re.I),
	re.compile(r"\bla narradora del b[úu]nker\b", re.I),
	re.compile(r"\bel (?:operador|ingeniero) catal[áa]n\b", re.I),
)


def looks_english(text: str) -> bool:
	"""¿La nota está en inglés? Recuento de palabras vacías EN vs ES (determinista)."""
	words = re.findall(r"[a-záéíóúüñ]+", text.lower())
	en = sum(w in _EN_WORDS for w in words)
	es = sum(w in _ES_WORDS for w in words)
	return en > es and en >= 3


def is_first_person(text: str) -> bool:
	"""True si la nota tiene marcadores de 1ª persona (criterio del rewrite)."""
	return bool(_FIRST_PERSON.search(text))


def quality_flags(text: str) -> List[str]:
	"""Detectores MEM-006 P2: género femenino de Joan, identidad confundida, voz 3ª."""
	flags: List[str] = []
	if _FEMININE_JOAN.search(text):
		flags.append("gender")
	if _IDENTITY_CONFUSION.search(text):
		flags.append("identity")
	if _THIRD_PERSON.search(text) or _IMPERSONAL.search(text) or _ALETH_PAST.search(text):
		flags.append("voice")
	return flags


def _normalize(text: str) -> str:
	return re.sub(r"[^a-z0-9áéíóúüñ ]+", " ", text.lower()).strip()


def _tokens(text: str) -> set:
	return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))


# Mínimo de tokens compartidos para declarar near-dup. La contención sobre notas
# cortas dispara con vocabulario compartido (AD-152: a t=0,60 y 949 notas reales,
# TODOS los colapsos eran notas distintas de 14-23 tokens que hablaban del mismo
# tema; 12 tokens compartidos quita esos falsos positivos sin perder duplicados
# reales, que rondan 15+ tokens en común).
_NEAR_DUP_MIN_SHARED = 12


def _note_text(a: Dict[str, Any]) -> str:
	return str(a.get("text") or "")


def _near_dup(a: set, b: set, threshold: float) -> bool:
	"""Contención sobre el conjunto menor, con masa mínima de tokens (AD-152).

	Misma función para el dedup, la métrica y el gate: si divergen, el gate pide
	lo que el dedup nunca deja de dejar (el 392 de near_dups de 2026-11-28).
	"""
	if not a or not b:
		return False
	inter = len(a & b)
	if inter < _NEAR_DUP_MIN_SHARED:
		return False
	return inter / min(len(a), len(b)) > threshold


def near_dup_pairs(texts: List[str], threshold: float) -> int:
	"""Pares near-dup en un conjunto de textos (medida diagnóstica, no de trabajo)."""
	toks = [_tokens(t) for t in texts]
	pairs = 0
	for i in range(len(toks)):
		for j in range(i + 1, len(toks)):
			if _near_dup(toks[i], toks[j], threshold):
				pairs += 1
	return pairs


def collapsible_notes(annotations: List[Dict[str, Any]], threshold: float) -> int:
	"""Notas que el dedup colapsaría (la unidad de trabajo del P1-A).

	Un par residual no es trabajo pendiente: dos notas distintas pueden compartir
	vocabulario y una nota puede aparecer en varios pares. Esta cuenta es
	exactamente lo que un pase de dedup eliminaría, así que `0` es el punto fijo
	alcanzable que el gate puede exigir.
	"""
	return len(annotations) - len(dedup_annotations(annotations, threshold))


def _rank(a: Dict[str, Any]) -> Tuple[int, float, int]:
	flags = a.get("flags") or []
	voice_ok = 0 if "voice" in flags else 1
	try:
		sig = float(a.get("significance") or 0)
	except (TypeError, ValueError):
		sig = 0.0
	return (voice_ok, sig, len(str(a.get("text") or "")))


def compute_note_metrics(annotations: List[Dict[str, Any]], *, dedup_threshold: float) -> Dict[str, Any]:
	"""Métricas de calidad de una sesión anotada (deterministas, sin IO).

	`near_dups` es diagnóstico (pares) y `dedup_collapsible` es la señal del gate
	(notas que el dedup borraría con esta misma política). Ambos salen de la
	misma señal —el texto, sin título— y de la misma función `_near_dup`.
	"""
	texts = [_note_text(a) for a in annotations]
	n = len(texts)
	lens = [len(t) for t in texts]
	margins = [
		abs(float(a.get("work_score", 0.0) or 0.0) - float(a.get("social_score", 0.0) or 0.0))
		for a in annotations
		if "work_score" in a and "social_score" in a
	]
	return {
		"notas": n,
		"pct_gt_600": round(100 * sum(1 for x in lens if x > 600) / max(1, n), 1),
		"pct_primera_persona": round(100 * sum(1 for t in texts if is_first_person(t)) / max(1, n), 1),
		"near_dups": near_dup_pairs(texts, dedup_threshold),
		"dedup_collapsible": collapsible_notes([{"text": t} for t in texts], dedup_threshold),
		"dedup_threshold": float(dedup_threshold),
		"min_margin": round(min(margins), 3) if margins else None,
		"bio_leaks": sum(1 for t in texts if any(p.search(t) for p in _BIO_LEAK_PATTERNS)),
	}


def dedup_annotations(annotations: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
	"""P1-A: colapsa duplicados exactos (hash normalizado) y near-dups (tokens).

	La señal es SOLO el texto (AD-152): el título llega vacío en annotate y en el
	resto lo escribe otro prompt, así que no dice nada sobre si dos notas son el
	mismo hecho; además dos notas distintas sobre el mismo tema comparten título.
	Conserva la mejor variante: 1ª persona > significance > longitud. Los gemelos
	work/social del mismo evento se funden aquí.
	"""
	kept: List[Dict[str, Any]] = []
	kept_tokens: List[set] = []
	seen: set = set()
	for a in sorted(annotations, key=_rank, reverse=True):
		text = _note_text(a)
		h = hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()
		if h in seen:
			continue
		t = _tokens(text)
		if any(_near_dup(t, kt, threshold) for kt in kept_tokens):
			continue
		seen.add(h)
		kept.append(a)
		kept_tokens.append(t)
	return kept
