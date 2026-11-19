"""MEM-012 · abstención — confianza categórica sobre la SIMILITUD del recall.

La señal es `hit.score` (similitud), nunca `reinforcement_score` (utilidad):
medido en F0, los aciertos puntúan 0,41-0,83 de similitud y los negativos
0,17-0,35, mientras la utilidad solapa. La decisión de abstenerse se toma sobre
`max(similarity)` de la **ventana de inyección** (top-3): con 10 candidatos el
negativo más duro sube a 0,3866 y el suelo deja de separar.

Bandas (D-AB-05, medidas en F0 el 2026-11-18 con 35 casos):

- `insuficiente`: max_sim < 0,38 (suelo ratificado)
- `baja`:         0,38  ≤ max_sim < 0,4551 (p10 de los positivos)
- `media`:        0,4551 ≤ max_sim < 0,592 (p25)
- `alta`:         max_sim ≥ 0,592

Los cortes viven en config (`SW_RECALL_ABSTENTION_FLOOR`,
`SW_RECALL_CONFIDENCE_MEDIA`, `SW_RECALL_CONFIDENCE_ALTA`): cambiar el número
no es cambiar la lógica. Este módulo es puro: no toca Qdrant ni LLM. F1 lo usa
para etiquetar la consulta; F2 lo usará para construir `no_recall`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

INSUFFICIENT = "insuficiente"
LOW = "baja"
MEDIUM = "media"
HIGH = "alta"

# Defaults = los de config; se aceptan explícitos para poder medir y testear
# bandas alternativas sin reescribir el singleton.
DEFAULT_FLOOR = 0.38
DEFAULT_MEDIA = 0.4551
DEFAULT_ALTA = 0.592


def similarity(hit: Any) -> float:
	"""Similitud del hit: `score`, jamás `reinforcement_score` (D-AB-01)."""
	try:
		return float(getattr(hit, "score", 0.0) or 0.0)
	except (TypeError, ValueError):
		return 0.0


def max_similarity(hits: Iterable[Any]) -> float:
	"""Máximo de similitud de la ventana; 0.0 si no hay hits.

	Se calcula sobre los hits que el llamante recibe (top-3), no sobre el top-1:
	con hybrid + MMR + boost el primero fusionado puede no ser el más similar
	(medido: 0,19 de top-1 frente a 0,83 de max en el mismo acierto).
	"""
	return max((similarity(hit) for hit in hits), default=0.0)


def confidence(
	max_sim: float,
	floor: float = DEFAULT_FLOOR,
	media: float = DEFAULT_MEDIA,
	alta: float = DEFAULT_ALTA,
) -> str:
	"""Categoría de confianza para una consulta.

	`>=` deja pasar: un hit exactamente en el suelo NO es insuficiente, y uno
	exactamente en `media`/`alta` entra en la banda superior.
	"""
	if max_sim < floor:
		return INSUFFICIENT
	if max_sim < media:
		return LOW
	if max_sim < alta:
		return MEDIUM
	return HIGH


def is_below_floor(max_sim: float, floor: float = DEFAULT_FLOOR) -> bool:
	"""¿La consulta no alcanza el suelo? (La puerta de D-AB-04 se ofrece igual.)"""
	return max_sim < floor


def alternatives_for(confidence_level: str) -> list:
	"""Salidas honestas cuando la confianza no basta (D-AB-03/D-AB-04).

	No inventan: ofrecen otro camino. `memento_fulltext` es la búsqueda literal
	sobre el árbol de Memento (F4 la ofrecerá sin ejecutarla sola).
	"""
	if confidence_level == INSUFFICIENT:
		return ["memento_fulltext", "replantear", "ampliar"]
	if confidence_level == LOW:
		return ["memento_fulltext", "ampliar"]
	return []


def passes_injection(
	sim: float,
	floor: float = DEFAULT_FLOOR,
	intent_threshold: float = 0.0,
	immune: bool = False,
) -> bool:
	"""¿Este hit entra al contexto en la postura de INYECCIÓN? (I-06, C-09)

	- Los inmunes/directivas no cambian de comportamiento (I-03): se les exime del
	suelo NUEVO, pero conservan el umbral de intención que ya tenían.
	- Para el resto, el umbral efectivo es el más alto de suelo e intención: la
	inyección nunca es más laxa que el suelo.
	- `threshold <= 0` ⇒ puerta abierta (C-07: apagar el suelo no abstiene; una
	similitud negativa tampoco).
	"""
	threshold = intent_threshold if immune else max(floor, intent_threshold)
	if threshold <= 0:
		return True
	return sim >= threshold


def build_abstention(
	hits: Iterable[Any],
	*,
	collection: str,
	floor: float = DEFAULT_FLOOR,
	media: float = DEFAULT_MEDIA,
	alta: float = DEFAULT_ALTA,
	include_below_floor: bool = False,
	exempt: bool = False,
	searched: Any = None,
) -> dict:
	"""Objeto `no_recall` de MEM-012 (F2).

	- `hits`: los que alcanzan el suelo, con su similitud y su banda.
	- `below_floor_count`: cuántos se quedaron fuera — viaja **siempre**.
	- `below_floor`: solo se materializa con `include_below_floor=True` (D-AB-04).
	- `no_recall`: no hay nada que alcance el suelo. Con `floor<=0` nunca se
	abstiene (C-07), y con `exempt` (directivas) tampoco (I-03).
	"""
	rows: List[Dict[str, Any]] = []
	for hit in hits:
		sim = similarity(hit)
		rows.append(
			{
				"id": str(getattr(hit, "id", "")),
				"similarity": sim,
				"confidence": confidence(sim, floor, media, alta),
				"payload": getattr(hit, "payload", None) or {},
			}
		)
	above = [row for row in rows if (floor <= 0 or row["similarity"] >= floor)]
	below = [row for row in rows if not (floor <= 0 or row["similarity"] >= floor)]
	if exempt:
		# I-03: las directivas no cambian de comportamiento; no se retiene ninguna.
		above, below = rows, []
	max_sim = max((row["similarity"] for row in rows), default=0.0)
	level = confidence(max_sim, floor, media, alta)
	no_recall = bool(floor > 0 and not exempt and max_sim < floor)
	out = {
		"no_recall": no_recall,
		"confidence": level,
		"max_similarity": round(max_sim, 4),
		"searched": searched or {"collection": collection, "strategy": "unknown", "anchors": []},
		"hits": above,
		"below_floor_count": len(below),
		"alternatives": alternatives_for(level),
	}
	if include_below_floor:
		out["below_floor"] = below
	return out
