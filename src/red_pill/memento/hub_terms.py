"""Términos-ancla del hub como índice (HUB-RECALL-001, D-02/D-02b).

Un hub es una IDEA con anclas, no una historia. `select_hub_terms` elige esas
anclas de forma determinista y acotada para que el hub participe en la pata
keyword del recall (`hub_keyword_hits`).

Regla de presupuesto (D-02, Operador 2026-11-09): se acumulan keywords ENTERAS
por relevancia; si el total actual es < `max_chars` se añade la siguiente
aunque el total pase el tope; si ya es >= `max_chars` se para. Nunca se corta
una keyword. `min_score` permite cortar la cola antes.

La política (pesos/stoplist) vive en `configs/hub_keyword_policy.yaml`; el
código solo aporta los valores por defecto si el fichero no está.
"""

from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

# Mismo alfabeto que el tokenizador de Memento: identificadores con dígito o
# `-_.` cuentan como ancla (BIT-003, tree_hash, v7.22.0, sub/fichero.py).
_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_.\-/]{2,}")

_DEFAULT_STOPLIST = {
	"plan",
	"planes",
	"estrategia",
	"estrategias",
	"ademas",
	"además",
	"entonces",
	"aunque",
	"mientras",
	"despues",
	"después",
	"finalmente",
	"luego",
	"sesion",
	"sesión",
	"sesiones",
	"revision",
	"revisión",
	"ajustes",
	"cambio",
	"cambios",
	"problema",
	"problemas",
	"mejora",
	"mejoras",
	"resolucion",
	"resolución",
	"continuacion",
	"continuación",
	"identidad",
	"datos",
	"tecnico",
	"técnico",
	"tecnicos",
	"técnicos",
	"general",
	"varios",
	"nueva",
	"nuevo",
	"nuevos",
	"nuevas",
	"parte",
	"partes",
	"tema",
	"temas",
	"cosa",
	"cosas",
}

_DEFAULT_POLICY: Dict[str, Any] = {
	"version": 1,
	"max_chars": 500,
	"max_terms": 128,
	"min_term_chars": 4,
	"min_score": 0.0,
	"weights": {"anchor": 2.0, "proper": 0.4, "title": 1.2, "length": 0.05},
	"stoplist": sorted(_DEFAULT_STOPLIST),
}


def _policy_path() -> Optional[Path]:
	override = os.environ.get("HUB_KEYWORD_POLICY_PATH")
	if override:
		return Path(override).expanduser()
	# src/red_pill/memento/hub_terms.py -> repo root/configs/...
	return Path(__file__).resolve().parents[3] / "configs" / "hub_keyword_policy.yaml"


@lru_cache(maxsize=1)
def load_policy() -> Dict[str, Any]:
	"""Carga la política YAML; cualquier fallo cae a los defaults del módulo."""
	policy = dict(_DEFAULT_POLICY)
	policy["weights"] = dict(_DEFAULT_POLICY["weights"])
	policy["stoplist"] = list(_DEFAULT_POLICY["stoplist"])
	path = _policy_path()
	if not path or not path.is_file():
		return policy
	try:
		raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
		if isinstance(raw, Mapping):
			for key in ("max_chars", "max_terms", "min_term_chars", "min_score", "version"):
				if key in raw:
					policy[key] = raw[key]
			weights = raw.get("weights")
			if isinstance(weights, Mapping):
				policy["weights"].update({str(k): float(v) for k, v in weights.items()})
			stoplist = raw.get("stoplist")
			if isinstance(stoplist, list):
				policy["stoplist"] = [str(item).strip() for item in stoplist if str(item).strip()]
	except Exception:
		pass
	return policy


def _extra_stopwords() -> set:
	"""Stoplist base de Memento (genéricos ES/EN) sin acoplar el módulo."""
	try:
		from red_pill.memento.hybrid import _STOP

		return {str(item).lower() for item in _STOP}
	except Exception:
		return set()


def _stopwords(policy: Mapping[str, Any]) -> set:
	configured = {str(item).lower() for item in (policy.get("stoplist") or [])}
	return configured | _extra_stopwords() | _DEFAULT_STOPLIST


def is_stopword(term: str, policy: Optional[Mapping[str, Any]] = None) -> bool:
	"""¿El término es un genérico de la stoplist (configurada + base de Memento)?"""
	pol: Mapping[str, Any] = policy if policy is not None else load_policy()
	return term.strip().lower() in _stopwords(pol)


def is_anchor(term: str) -> bool:
	"""¿Es un ancla? Identificador, ruta, versión, número o acrónimo/nombre propio."""
	if not term:
		return False
	if any(ch.isdigit() for ch in term):
		return True
	if any(ch in "-_./" for ch in term):
		return True
	if term[:1].isupper():
		return True
	if len(term) > 2 and term.isupper():
		return True
	return False


def is_anchor_occurrence(term: str, lower_seen: set) -> bool:
	"""¿La ocurrencia concreta es ancla? Una Mayúscula inicial de frase NO lo es.

	`is_anchor` no conoce el contexto; aquí sí: una palabra que también aparece
	en minúsculas en el texto es una palabra común al inicio de frase, no un
	nombre propio. Los identificadores/rutas/números/acrónimos siguen siendo
	anclas siempre.
	"""
	if not is_anchor(term):
		return False
	if any(ch.isdigit() or ch in "-_./" for ch in term):
		return True
	if len(term) > 2 and term.isupper():
		return True
	return term.lower() not in lower_seen


def tokenize(text: str) -> List[str]:
	"""Tokens con el alfabeto de Memento, sin los delimitadores de borde."""
	terms: List[str] = []
	for raw in _TOKEN_RE.findall(text or ""):
		term = raw.strip(".-_/")
		if term:
			terms.append(term)
	return terms


def _stem(term: str) -> str:
	"""Stem ES mínimo para deduplicar plurales (suficiente para anclas)."""
	low = term.lower()
	if len(low) > 6 and low.endswith("es"):
		return low[:-2]
	if len(low) > 4 and low.endswith("s"):
		return low[:-1]
	return low


def _score(term: str, tf: int, title: str, policy: Mapping[str, Any], anchored: bool) -> float:
	weights = policy.get("weights") or {}
	anchor = 1.0 if anchored else 0.0
	proper = 1.0 if term[:1].isupper() else 0.0
	in_title = 1.0 if term.lower() in title else 0.0
	length = min(len(term), 20)
	return (
		(1.0 + float(weights.get("anchor", 2.0)) * anchor + float(weights.get("proper", 0.4)) * proper + float(weights.get("title", 1.2)) * in_title)
		* (1.0 + math.log1p(max(1, tf)))
		* (1.0 + float(weights.get("length", 0.05)) * length)
	)


def select_hub_terms(
	text: str,
	title: str = "",
	max_chars: Optional[int] = None,
	policy: Optional[Mapping[str, Any]] = None,
) -> List[str]:
	"""Selecciona las anclas del hub con presupuesto BLANDO (D-02).

	Devuelve la lista de keywords enteras, sin cortar ninguna. El total de
	caracteres (`sum(len(t) for t in terms)`) puede superar `max_chars` como
	mucho por la última keyword añadida; nunca por una keyword partida.
	"""
	pol: Mapping[str, Any] = policy if policy is not None else load_policy()
	budget = int(max_chars if max_chars is not None else pol.get("max_chars", 500))
	max_terms = int(pol.get("max_terms", 128))
	min_chars = int(pol.get("min_term_chars", 4))
	min_score = float(pol.get("min_score", 0.0))
	stop = _stopwords(pol)
	title_low = (title or "").lower()

	counts: Dict[str, int] = {}
	original: Dict[str, str] = {}
	tokens = tokenize(text)
	lower_seen = {term.lower() for term in tokens if term == term.lower()}
	for term in tokens:
		low = term.lower()
		if len(term) < min_chars and not is_anchor(term):
			continue
		if low in stop:
			continue
		stem = _stem(term)
		counts[stem] = counts.get(stem, 0) + 1
		# Representante: conserva la forma con más señal (mayúscula/dígito).
		prev = original.get(stem)
		if prev is None or (is_anchor(term) and not is_anchor(prev)):
			original[stem] = term

	ranked: List[Tuple[float, str]] = []
	for stem, tf in counts.items():
		term = original[stem]
		ranked.append((_score(term, tf, title_low, pol, is_anchor_occurrence(term, lower_seen)), term))
	ranked.sort(key=lambda item: (-item[0], -len(item[1]), item[1].lower()))

	selected: List[str] = []
	total = 0
	for score, term in ranked:
		if total >= budget:
			break
		if score < min_score and not is_anchor(term):
			break
		selected.append(term)
		total += len(term)
		if len(selected) >= max_terms:
			break
	return selected


def hub_terms_chars(terms: Iterable[str]) -> int:
	"""Longitud total de la lista de anclas (sin separadores; es un payload)."""
	return sum(len(str(term)) for term in terms)


def hub_search_text(payload: Mapping[str, Any]) -> str:
	"""Texto de matching keyword del hub: título + anclas (fallback: content).

	Los hubs viejos (v0/v2) no tienen `hub_terms`; se usa su `content` para que
	sigan siendo recuperables sin migrarlos (D-11).
	"""
	title = str(payload.get("hub_title") or "")
	terms = payload.get("hub_terms") or []
	if isinstance(terms, (list, tuple)) and terms:
		return (title + " " + " ".join(str(t) for t in terms)).strip()
	return str(payload.get("content") or title)


def term_idf(total_docs: int, doc_freq: int) -> float:
	"""IDF suavizado sobre el corpus de hubs escaneado."""
	if total_docs <= 0:
		return 0.0
	return math.log(1.0 + total_docs / (1.0 + max(0, doc_freq)))
