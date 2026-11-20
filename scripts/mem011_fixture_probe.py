#!/usr/bin/env python3
"""MEM-011 · F3 — fixture desechable con el árbol hoja → parte → raíz.

Por qué existe: la medida de F3 del 2026-11-17 se hizo con una sonda y un fixture
que vivían en `/tmp/opencode` — el directorio que no sobrevive a un reinicio. La
medida del 2026-11-18 sobre el Búnker vivo fue honesta pero vacía: con
`SW_HUB_POLAROID_ENABLED=off` no hay partes y el enrutado es inerte (11/11 casos,
mismo ranking). Este script reconstruye el experimento de forma reproducible y
**sin escribir en el Búnker**:

1. **Corpus real, árbol sintético**: copia en un Qdrant local (`:memory:`) los
	puntos vivos con sus vectores y payloads. La única variable es la jerarquía.
2. **Árbol**: cada sesión con ≥2 miembros se empaqueta con el plan de F1
	(`plan_session_parts`: polaroids enteras fusionadas hasta el presupuesto) y sus
	hojas se re-parentan a su parte (`hub_id=<parte>, hubbed=True`). La raíz
	conserva su resumen REAL; las partes llevan un resumen **stand-in**
	determinista (concatenación recortada por miembro). No se sintetiza con LLM a
	propósito: 18 llamadas convertirían la medida del enrutado en una medida del
	sintetizador. Lo que se mide aquí es el ranking, no la calidad del resumen.
3. **Matriz**: `SW_RECALL_LEAF_ROUTING` ∈ {off, replace, rescue} ×
	`SW_RECALL_LEAF_AGG` ∈ {max, mean_top3}, reconstruyendo el cliente en cada
	pasada: el recall refuerza lo que recupera, así que sin reconstruir cada modo
	mediría el corpus que dejó el anterior. **En `next` solo existe `off`**: el
	enrutado por hoja se midió con este fixture y se rechazó; los modos viven en
	la rama histórica `feat/mem011-f0`.

Lo que el fixture SÍ prueba: que una hoja rinde a su raíz (dos saltos), que una
parte no vuelve nunca como nodo primario (D-SH-01/I-08) y cómo cambia el puesto
del detalle con cada agregación.

Lo que NO prueba: si la síntesis real conserva el detalle (eso es F5 con el flag
ON), ni el suelo de abstención (necesita MEM-012 F0 con negativos duros).

Uso:
	python3 scripts/mem011_fixture_probe.py --agg max,mean_top3
	python3 scripts/mem011_fixture_probe.py --modes replace,rescue --out /tmp/mem011-fixture.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CASES_DEFAULT = Path(__file__).with_name("mem011_recall_cases.json")
NEEDED = ("name", "query", "collection", "expect")
VECTOR_SIZE = 384


# ── corpus ────────────────────────────────────────────────────────────────────


def _is_hub(payload: Dict[str, Any]) -> bool:
	return payload.get("node_type") == "synthesis_hub" or payload.get("lazarus_phase") == "synthesis_hub"


def load_snapshot(manager: Any, collections: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
	"""Copia read-only del Búnker: id, vector y payload de cada punto."""
	out: Dict[str, List[Dict[str, Any]]] = {}
	for collection in collections:
		points: List[Dict[str, Any]] = []
		offset = None
		while True:
			batch, offset = manager.client.scroll(
				collection_name=collection,
				limit=512,
				offset=offset,
				with_payload=True,
				with_vectors=True,
			)
			for point in batch:
				if point.vector is None:
					continue
				vector = point.vector if not isinstance(point.vector, dict) else next(iter(point.vector.values()), None)
				if vector is None:
					continue
				points.append({"id": str(point.id), "vector": list(vector), "payload": dict(point.payload or {})})
			if offset is None:
				break
		out[collection] = points
	return out


def build_tree(
	master: Sequence[Dict[str, Any]],
	collection: str,
	budget: int,
	embed: Any,
	stats: Counter,
) -> List[Dict[str, Any]]:
	"""Aplana y reconstruye el árbol: re-parenta las hojas a sus partes.

	Devuelve puntos nuevos (no muta `master`). Las sesiones sin raíz propia o sin
	polaroids resolubles se dejan como están —re-parentarlas a una parte sin raíz
	crearía exactamente la cadena rota que el enrutado descarta—.
	"""
	from red_pill.memento.hub_terms import select_hub_terms
	from red_pill.metabolism.hub_parts import part_point_id, plan_session_parts
	from red_pill.metabolism.hub_synthesis import hub_point_id

	points = [{"id": p["id"], "vector": p["vector"], "payload": dict(p["payload"])} for p in master]
	by_session: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
	for point in points:
		payload = point["payload"]
		if payload.get("node_type") == "memento_engram" and payload.get("session_id"):
			by_session[str(payload["session_id"])].append(point)
	hub_ids = {p["id"] for p in points if _is_hub(p["payload"])}

	parts: List[Dict[str, Any]] = []
	for session_id in sorted(by_session):
		members = by_session[session_id]
		if len(members) < 2:
			continue
		stats["sessions"] += 1
		plan = plan_session_parts(session_id, [(m["id"], m["payload"]) for m in members], budget)
		if not plan["needs_parts"]:
			stats["single"] += 1
			continue
		root_id = hub_point_id(collection, session_id)
		if root_id not in hub_ids:
			stats["no_root"] += 1
			continue
		stats["with_parts"] += 1
		for part in plan["parts"]:
			if not part.members:
				continue
			part_id = part_point_id(collection, session_id, part.part_key)
			ordered = sorted(part.members, key=lambda m: (float((m[1] or {}).get("created_at") or 0.0), str(m[0])))
			body = "\n\n".join(str((pl or {}).get("content") or "")[:600] for _mid, pl in ordered)[:budget]
			title = ""
			for _mid, pl in ordered:
				first = str((pl or {}).get("content") or "").strip().split("\n", 1)[0]
				if first:
					title = first[:80]
					break
			text = f"{title}\n{body}" if title else body
			created = [float((pl or {}).get("created_at") or 0.0) for _mid, pl in ordered if (pl or {}).get("created_at")]
			parts.append(
				{
					"id": part_id,
					"vector": embed(text),
					"payload": {
						"node_type": "synthesis_hub",
						"lazarus_phase": "synthesis_hub",
						"hub_role": "part",
						"hub_id": root_id,
						"part_key": part.part_key,
						"hub_key": f"{collection}:{session_id}:{part.part_key}",
						"hub_depth": 1,
						"session_id": session_id,
						"origin": "memento_hub",
						"content": body,
						"hub_title": title,
						"hub_terms": select_hub_terms(body, title=title),
						"hub_members_count": len(part.members),
						"created_at": min(created) if created else 0.0,
						"reinforcement_score": 5.0,
						"immune": False,
						"color": "neutral",
						"emotion": "neutral",
						"intensity": 0.5,
						# Marca de fixture: si aparece en una medida del Búnker, algo
						# escribió donde no debía.
						"fixture": "mem011",
					},
				}
			)
			stats["parts"] += 1
			by_id = {p["id"]: p for p in members}
			for member_id, _payload in part.members:
				node = by_id.get(str(member_id))
				if node is not None:
					node["payload"]["hub_id"] = part_id
					node["payload"]["hubbed"] = True
	return points + parts


# ── cliente efímero ───────────────────────────────────────────────────────────


def make_client(points_by_collection: Dict[str, List[Dict[str, Any]]]) -> Any:
	from qdrant_client import QdrantClient, models

	client = QdrantClient(location=":memory:")
	for collection, points in points_by_collection.items():
		client.create_collection(
			collection_name=collection,
			vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
		)
		for start in range(0, len(points), 256):
			client.upsert(
				collection_name=collection,
				points=[models.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points[start : start + 256]],
			)
	return client


# ── medida ────────────────────────────────────────────────────────────────────


def _norm(text: Any) -> str:
	return str(text or "").lower()


def detail_rank(rows: Sequence[Dict[str, Any]], expect: Sequence[str]) -> Optional[int]:
	needles = [_norm(n) for n in expect if n]
	if not needles:
		return None
	for row in rows:
		if all(n in _norm(row.get("content")) for n in needles):
			return int(row["rank"])
	return None


def case_rows(hits: Sequence[Any]) -> List[Dict[str, Any]]:
	rows: List[Dict[str, Any]] = []
	for rank, hit in enumerate(hits, start=1):
		payload = getattr(hit, "payload", None) or {}
		rows.append(
			{
				"rank": rank,
				"id": str(getattr(hit, "id", "")),
				"score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
				"role": payload.get("hub_role") or ("root" if _is_hub(payload) else payload.get("node_type")),
				"session": payload.get("session_id") or "",
				"content": payload.get("content") or "",
				"entry_leaf": (payload.get("_entry_leaf") or {}).get("id"),
			}
		)
	return rows


def load_cases(path: Path) -> List[Dict[str, Any]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	cases = data["cases"] if isinstance(data, dict) else data
	for case in cases:
		missing = [k for k in NEEDED if k not in case]
		if missing:
			raise SystemExit(f"[fixture] caso {case.get('name', '?')} sin campos: {missing}")
	return cases


def run_mode(
	manager: Any,
	client: Any,
	cases: Sequence[Dict[str, Any]],
	mode: str,
	agg: str,
	limit: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
	manager.client = client
	manager._hub_ids_cache = {}
	# El enrutado por hoja no está en `next` (se midió y se rechazó): el
	# instrumento mide la línea base `off`. Los otros modos solo existen en la
	# rama histórica `feat/mem011-f0`.
	if hasattr(manager.cfg, "SW_RECALL_LEAF_ROUTING"):
		manager.cfg.SW_RECALL_LEAF_ROUTING = mode
	if hasattr(manager.cfg, "SW_RECALL_LEAF_AGG"):
		manager.cfg.SW_RECALL_LEAF_AGG = agg
	out: List[Dict[str, Any]] = []
	breaches = {"parts_in_primary": 0, "routed_rows": 0}
	for case in cases:
		hits = manager._search_and_reinforce_impl(
			collection=case["collection"],
			query=case["query"],
			limit=limit,
			hybrid=False,
		)
		rows = case_rows(hits)
		breaches["parts_in_primary"] += sum(1 for row in rows if row["role"] == "part")
		breaches["routed_rows"] += sum(1 for row in rows if row["entry_leaf"])
		rank = detail_rank(rows, case["expect"])
		out.append(
			{
				"name": case["name"],
				"kind": case.get("kind", "must"),
				"detail_rank": rank,
				# Ventana honesta: el número de filas que el llamante ve varía por
				# modo (`replace` llega a devolver 18 para un limit=3, porque el
				# enrutado no se trunca). Comparar puestos a distinta ventana premia
				# al que enseña más filas, no al que acierta.
				"detail_in_window": rank is not None and rank <= limit,
				"rows_returned": len(rows),
				"top": rows[0]["score"] if rows else None,
				"top_role": rows[0]["role"] if rows else None,
				"rows": rows,
			}
		)
	return out, breaches


def main(argv: Optional[Sequence[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="MEM-011 F3 — fixture del árbol (read-only sobre el Búnker)")
	parser.add_argument("--cases", type=Path, default=CASES_DEFAULT)
	parser.add_argument("--modes", default="off,replace,rescue")
	parser.add_argument("--agg", default="max,mean_top3")
	parser.add_argument("--limit", type=int, default=3)
	parser.add_argument("--budget", type=int, default=0, help="chars por parte (default: hub_budget())")
	parser.add_argument("--out", type=Path, default=None)
	args = parser.parse_args(argv)

	cases = load_cases(args.cases)
	collections = sorted({case["collection"] for case in cases})
	modes = [m.strip() for m in args.modes.split(",") if m.strip()]
	aggs = [a.strip() for a in args.agg.split(",") if a.strip()]
	if modes != ["off"]:
		from red_pill.config import get_config_cached

		if not hasattr(get_config_cached(), "SW_RECALL_LEAF_ROUTING"):
			print("[fixture] sin enrutado por hoja en esta rama (rechazado); se mide solo off", file=sys.stderr)
			modes = ["off"]

	# El venv tiene `red_pill` instalado en modo editable apuntando al checkout
	# principal: desde un worktree, sin este guard, el script mediría `next` y no
	# la rama (el mismo pie que ya está documentado en `pyproject.toml`).
	import red_pill
	from red_pill.memory import MemoryManager
	from red_pill.metabolism.distiller import hub_budget

	expected = Path(__file__).resolve().parents[1] / "src"
	if not Path(red_pill.__file__).resolve().is_relative_to(expected):
		raise SystemExit(
			f"[fixture] red_pill importado desde {Path(red_pill.__file__).resolve()}, no desde {expected}. "
			f"Ejecuta con PYTHONPATH={expected} para medir el código de esta rama."
		)

	budget = args.budget or hub_budget()
	manager = MemoryManager()
	print(f"[fixture] corpus: {', '.join(collections)} · budget={budget}", file=sys.stderr)
	snapshot = load_snapshot(manager, collections)

	cache: Dict[str, List[float]] = {}

	def embed(text: str) -> List[float]:
		if text not in cache:
			cache[text] = manager._get_vector(text)
		return cache[text]

	stats: Counter = Counter()
	materialized: Dict[str, List[Dict[str, Any]]] = {}
	for collection in collections:
		materialized[collection] = build_tree(snapshot[collection], collection, budget, embed, stats)
		print(f"[fixture] {collection:<20} puntos={len(snapshot[collection])}", file=sys.stderr)
	print(
		f"[fixture] sesiones con plan={stats['sessions']} · con partes={stats['with_parts']} · "
		f"una sola parte={stats['single']} · sin raíz={stats['no_root']} · partes={stats['parts']}",
		file=sys.stderr,
	)

	report: Dict[str, Any] = {
		"budget": budget,
		"limit": args.limit,
		"corpus": {c: len(points) for c, points in materialized.items()},
		"tree": dict(stats),
		"matrix": {},
	}
	for agg in aggs:
		for mode in modes:
			client = make_client(materialized)
			rows, breaches = run_mode(manager, client, cases, mode, agg, args.limit)
			report["matrix"][f"{mode}|{agg}"] = {"cases": rows, "breaches": breaches}
			found = sum(1 for row in rows if row["detail_rank"] is not None)
			in_window = sum(1 for row in rows if row["detail_in_window"])
			returned = sum(row["rows_returned"] for row in rows)
			negative = next((row for row in rows if row["kind"] == "negative"), None)
			print(
				f"[fixture] {mode:<8} agg={agg:<9} detalle {found}/{len(rows)} · "
				f"en ventana {in_window}/{len(rows)} · filas {returned} · "
				f"negativo top={negative['top'] if negative else '-'} · "
				f"partes en primario={breaches['parts_in_primary']} · "
				f"filas ancladas={breaches['routed_rows']}",
				file=sys.stderr,
			)

	if args.out:
		args.out.write_text(json.dumps(report, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
		print(f"[fixture] volcado: {args.out}", file=sys.stderr)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
