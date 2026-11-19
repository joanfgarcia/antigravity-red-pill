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

from typing import Any, Iterable

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
