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


def _rank(a: Dict[str, Any]) -> Tuple[int, float, int]:
	flags = a.get("flags") or []
	voice_ok = 0 if "voice" in flags else 1
	try:
		sig = float(a.get("significance") or 0)
	except (TypeError, ValueError):
		sig = 0.0
	return (voice_ok, sig, len(str(a.get("text") or "")))


def compute_note_metrics(annotations: List[Dict[str, Any]], *, dedup_threshold: float) -> Dict[str, Any]:
	"""Métricas de calidad de una sesión anotada (deterministas, sin IO)."""
	texts = [str(a.get("text") or "") for a in annotations]
	n = len(texts)
	lens = [len(t) for t in texts]
	toks = [_tokens(t + " " + str(a.get("title") or "")) for t, a in zip(texts, annotations)]
	near_dups = 0
	for i in range(len(toks)):
		for j in range(i + 1, len(toks)):
			a, b = toks[i], toks[j]
			if a and b and len(a & b) / min(len(a), len(b)) > dedup_threshold:
				near_dups += 1
	margins = [
		abs(float(a.get("work_score", 0.0) or 0.0) - float(a.get("social_score", 0.0) or 0.0))
		for a in annotations
		if "work_score" in a and "social_score" in a
	]
	return {
		"notas": n,
		"pct_gt_600": round(100 * sum(1 for x in lens if x > 600) / max(1, n), 1),
		"pct_primera_persona": round(100 * sum(1 for t in texts if is_first_person(t)) / max(1, n), 1),
		"near_dups": near_dups,
		"dedup_threshold": float(dedup_threshold),
		"min_margin": round(min(margins), 3) if margins else None,
		"bio_leaks": sum(1 for t in texts if any(p.search(t) for p in _BIO_LEAK_PATTERNS)),
	}


def dedup_annotations(annotations: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
	"""P1-A: colapsa duplicados exactos (hash normalizado) y near-dups (tokens).

	Conserva la mejor variante: 1ª persona > significance > longitud. Los gemelos
	work/social del mismo evento se funden aquí.
	"""
	kept: List[Dict[str, Any]] = []
	kept_tokens: List[set] = []
	seen: set = set()
	for a in sorted(annotations, key=_rank, reverse=True):
		text = str(a.get("text") or "")
		h = hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()
		if h in seen:
			continue
		t = _tokens(text + " " + str(a.get("title") or ""))
		if any(t and kt and len(t & kt) / min(len(t), len(kt)) > threshold for kt in kept_tokens):
			continue
		seen.add(h)
		kept.append(a)
		kept_tokens.append(t)
	return kept
