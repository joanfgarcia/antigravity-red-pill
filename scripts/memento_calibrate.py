#!/usr/bin/env python3
"""memento_calibrate.py — calibración en sombra de la estabilidad polaroid (Fase 4 §6.9).

Antes de enforcear el gate de ascenso por refuerzo, se simula sobre el corpus real
(EN SOMBRA: no toca Qdrant ni el frontmatter) cuántos refine ascenderían con cada
combinación de (τ, GAIN, gate).

La simulación replica el weaver Memento-consciente (§4.2) a lo largo de N ciclos
nocturnos (uno por día): en cada ciclo, los engramas creados en la ventana
(`AXON_WINDOW_HOURS`) son los "temas" que refuerzan los refine afines. Cada refine
aplica decay exponencial entre ciclos + GAIN por aparición, y asciende si supera
el gate. Los temas se limpian (solo theme/texture/relics, sin el cuerpo del
engrama — el matching por tokens de contenido libre satura con 35K engramas).

Elige y reporta la combinación más cercana a un objetivo de ascensos sostenidos
(no saturar ni vaciar).

Uso:
	uv run python scripts/memento_calibrate.py
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from red_pill.memento.ascension import _refine_topics, _temas_afines, parse_refine

_ENGINEERING_STOPWORDS = {
	"sistema",
	"también",
	"nuestra",
	"nuestro",
	"cuando",
	"después",
	"entonces",
	"proyecto",
	"documento",
	"proceso",
	"manera",
	"forma",
	"mismo",
	"misma",
	"porque",
	"hacer",
	"puede",
	"todos",
	"todo",
	"cada",
	"donde",
	"parte",
	"entre",
	"sobre",
	"desde",
	"estado",
	"siendo",
	"tiempo",
	"podemos",
	"necesita",
	"buena",
	"bien",
	"the",
	"that",
	"with",
	"from",
	"this",
	"have",
	"been",
	"into",
	"and",
	"were",
	"will",
	"would",
	"should",
	"could",
	"about",
	"after",
	"before",
	"their",
}


def _clean_engram_topics(payload: Dict[str, Any]) -> set:
	"""Temas de un engrama SIN el cuerpo libre (el texto completo satura el índice):
	solo theme/texture/relics, tokens ≥5 chars, sin stopwords de ingeniería."""
	topics: set = set()
	texture = payload.get("texture")
	if isinstance(texture, dict):
		theme = texture.get("theme")
		if theme:
			topics.add(str(theme))
		for relic in texture.get("relics", []) or []:
			topics.update(_clean_tokens(relic))
	else:
		topics.update(_clean_tokens(texture))
	for key in ("theme", "relics", "keywords"):
		val = payload.get(key)
		if isinstance(val, str):
			topics.update(_clean_tokens(val))
		elif isinstance(val, list):
			for item in val:
				topics.update(_clean_tokens(item))
	return topics


def _clean_tokens(text: Any) -> set:
	if text is None:
		return set()
	out = set()
	for word in str(text).lower().replace("_", " ").replace("-", " ").split():
		word = "".join(ch for ch in word if ch.isalnum())
		if len(word) >= 5 and word not in _ENGINEERING_STOPWORDS:
			out.add(word)
	return out


def calibrate(
	root: Any = None,
	registry: Any = None,
	memory_manager: Any = None,
	window_hours: float = 24.0,
	n_cycles: int = 30,
	tau_grid: Tuple[float, ...] = (45.0, 90.0, 180.0),
	gain_grid: Tuple[float, ...] = (0.5, 1.0, 2.0),
	gate_grid: Tuple[float, ...] = (3.0, 4.0, 5.0, 7.0),
) -> Dict[str, Any]:
	"""Simula el refuerzo en sombra. Devuelve `refine_count`, `ciclos`, y `matrix`
	(lista de {tau, gain, gate, ascensos, pct})."""
	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()
	if root is None:
		from red_pill.memento import get_memento_root

		root = get_memento_root()
	if registry is None:
		from red_pill.memento.registry import MementoRegistry

		registry = MementoRegistry()

	client = memory_manager.client
	collections = [c for c in ("work_memories", "social_memories") if client.collection_exists(c)]

	# 1. Engramas con (created_at, temas limpios) + (cycletick del día).
	engramas: List[Tuple[int, set]] = []
	for col in collections:
		offset = None
		while True:
			batch, offset = client.scroll(collection_name=col, limit=128, with_payload=True, with_vectors=False, offset=offset)
			for point in batch:
				payload = point.payload or {}
				from red_pill.memento.render import _to_datetime

				created_dt = _to_datetime(payload.get("created_at"))
				if not created_dt:
					continue
				topics = _clean_engram_topics(payload)
				if topics:
					engramas.append((created_dt.timestamp(), topics))
			if offset is None:
				break

	# 2. Refine NO ascendidos → (path, theme, tokens limpios del refine).
	refines = []
	for refine_path in sorted(Path(root).rglob("refine/*.md")):
		fm, body = parse_refine(refine_path.read_text(encoding="utf-8"))
		if not body or fm.get("ascended"):
			continue
		refine_theme, refine_tokens = _refine_topics(fm, body)
		refines.append((refine_theme, refine_tokens))

	# 3. Simulación por ciclos (ventana deslizante de 1 día).
	now_max = max((t for t, _ in engramas), default=0.0)
	cycle_start = now_max - n_cycles * window_hours * 3600.0
	topics_per_cycle: List[set] = []
	for c in range(n_cycles):
		lo = cycle_start + c * window_hours * 3600.0
		hi = lo + window_hours * 3600.0
		cycle_topics: set = set()
		for t, topics in engramas:
			if lo <= t < hi:
				cycle_topics.update(topics)
		topics_per_cycle.append(cycle_topics)

	matrix = []
	for tau in tau_grid:
		for gain in gain_grid:
			for gate in gate_grid:
				ascensos = 0
				for theme, tokens in refines:
					S = 0.0
					last: float | None = None
					ascended = False
					for idx, cycle_topics in enumerate(topics_per_cycle):
						if not _temas_afines(theme, tokens, cycle_topics):
							continue
						t = cycle_start + (idx + 1) * window_hours * 3600.0
						if last is not None and tau > 0:
							S *= math.exp(-max(0.0, t - last) / 86400.0 / tau)
						S += gain
						if S >= gate:
							ascended = True
							break
						last = t
					ascensos += int(ascended)
				matrix.append({"tau": tau, "gain": gain, "gate": gate, "ascensos": ascensos, "pct": round(100 * ascensos / max(len(refines), 1), 1)})

	return {"refine_count": len(refines), "engramas": len(engramas), "ciclos": n_cycles, "matrix": matrix}


def main() -> None:
	parser = argparse.ArgumentParser(description="Calibración en sombra de τ/GAIN/gate del refuerzo polaroid.")
	parser.parse_args()

	result = calibrate()
	print(f"[CALIBRATE] {result['refine_count']} refine no ascendidos | {result['engramas']} engramas | {result['ciclos']} ciclos")
	print(f"{'τ(d)':>6} {'GAIN':>5} {'gate':>5} {'ascensos':>9} {'pct':>6}")
	best = None
	for row in result["matrix"]:
		mark = " "
		if 5.0 <= row["pct"] <= 20.0 and (best is None or row["gate"] > best["gate"]):
			best = row
			mark = "*"
		print(f"{row['tau']:>6.0f} {row['gain']:>5.1f} {row['gate']:>5.1f} {row['ascensos']:>9} {row['pct']:>5.1f} {mark}")
	if best:
		print(f"[CALIBRATE] recomendado: τ={best['tau']:.0f}d GAIN={best['gain']:.1f} gate={best['gate']:.1f} ({best['pct']:.1f}% ascenderían)")


if __name__ == "__main__":
	main()
