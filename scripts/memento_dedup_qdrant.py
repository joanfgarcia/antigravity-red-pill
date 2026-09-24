#!/usr/bin/env python3
"""memento_dedup_qdrant.py — P1-B (MEM-006): limpieza de duplicados ya sembrados en Qdrant.

QUÉ ES / PARA QUÉ
	Agrupa los engramas de `work_memories`/`social_memories` por
	`session_id+source_lines` y, dentro de cada grupo, por **hash del body
	normalizado** (Q3: hash exacto; el residuo de near-dups de P1-A es 1,9% y no
	exige embeddings). Los bodies idénticos son réplicas → deja UN superviviente
	por grupo y borra el resto **in-place** (sin re-resiembra). Dry-run por
	defecto con plan de borrado; `--apply` ejecuta (snapshot de seguridad antes).

	Superviviente (Q2, pesos tunables con `--weights`):
		score = w_sig*significance + w_cat*category_score + w_len*len_norm
			+ w_voz*voz_1a + w_int*intensity + w_eng*engine_granite
	Reglas duras (antes del score):
		- Si algún punto del grupo está REFERENCIADO (payloads de otros nodos:
			associations/cross_refs/miembros) → el superviviente sale de los
			referenciados (no se dejan aristas colgando). Empate → score.
		- Empate de score → significance, luego id (determinista).

USO
	uv run python scripts/memento_dedup_qdrant.py --dry-run
	uv run python scripts/memento_dedup_qdrant.py --dry-run --scope global --report /tmp/plan.json
	uv run python scripts/memento_dedup_qdrant.py --apply --scope global        # limpia (snapshot antes)
	uv run python scripts/memento_dedup_qdrant.py --apply --limit 50            # pasada cauta
	uv run python scripts/memento_dedup_qdrant.py --weights sig=1,cat=.5,len=.5,voz=.5,int=.3,eng=1
	--fix-seals: repunta los sellos `ascended_point_id` de Memento que apunten a
	perdedores hacia el superviviente (los reporta siempre el plan).

HISTORIA
	Nace del RFC MEM-006 P1-B (2026-09-17) y del gap MEM-007 G5 (2026-09-23):
	la ronda de redestilado del fix de sesiones grandes sembró ~1,5k réplicas
	exactas (cohortes granite/legacy). La cata del 40% (2026-09-23) confirmó que
	la cohorte tiny_aya está limpia (0,1%) y fijó la magnitud real a limpiar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FIRST_PERSON_RE = re.compile(r"\b(me|mi|mis|yo|nos|nosotr[oa]s|nuestr[oa]s?|le explico|conté|hablé|dije|propuse)\b", re.IGNORECASE)

DEFAULT_WEIGHTS = {"sig": 1.0, "cat": 0.5, "len": 0.5, "voz": 0.5, "int": 0.3, "eng": 1.0}


def body_hash(content: Any) -> str:
	"""Hash del body normalizado (minúsculas + espacios colapsados) — Q3."""
	return hashlib.sha1(" ".join(str(content or "").lower().split()).encode("utf-8")).hexdigest()


def engine_score(engine: Any) -> float:
	e = str(engine or "").lower()
	if "granite" in e:
		return 1.0
	if "tiny" in e:
		return 0.0
	return 0.5


def _f(payload: Dict[str, Any], key: str, default: float = 0.0) -> float:
	try:
		value = payload.get(key)
		return float(default if value is None else value)
	except (TypeError, ValueError):
		return default


def score_point(point: Dict[str, Any], weights: Dict[str, float]) -> tuple:
	"""Score compuesto (Q2) + componentes, para el plan."""
	pl = point["payload"]
	content = str(pl.get("content") or "")
	cat = _f(pl, "work_score") if point["collection"] == "work_memories" else _f(pl, "social_score")
	components = {
		"sig": min(max(_f(pl, "significance"), 0.0), 1.0),
		"cat": min(max(cat, 0.0), 1.0),
		"len": min(len(content) / 800.0, 1.0),
		"voz": 1.0 if FIRST_PERSON_RE.search(content) else 0.0,
		"int": min(max(_f(pl, "intensity"), 0.0), 1.0),
		"eng": engine_score(pl.get("engine")),
	}
	return round(sum(weights[k] * v for k, v in components.items()), 6), components


def collect_referenced_ids(points: List[Dict[str, Any]]) -> set:
	"""Ids de puntos referenciados por el payload de CUALQUIER nodo (listas/dicts)."""
	ids = {p["id"] for p in points}
	referenced: set = set()

	def walk(value: Any) -> None:
		if isinstance(value, str):
			if value in ids:
				referenced.add(value)
		elif isinstance(value, (list, tuple)):
			for item in value:
				walk(item)
		elif isinstance(value, dict):
			for item in value.values():
				walk(item)

	for p in points:
		walk(p["payload"])
	return referenced


def build_plan(
	points: List[Dict[str, Any]],
	weights: Optional[Dict[str, float]] = None,
	scope: str = "source",
	route_resolver: Optional[Any] = None,
) -> Dict[str, Any]:
	"""Plan de borrado determinista.

	`scope`: `source` (RFC P1-B: colección+sesión+líneas+body) · `collection`
	(colección+body) · `global` (body a secas, cruzando colecciones — la
	duplicación real: el mismo engrama sembrado en work Y social).
	"""
	weights = dict(weights or DEFAULT_WEIGHTS)
	referenced = collect_referenced_ids(points)
	groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
	sin_clave: List[str] = []
	for p in points:
		pl = p["payload"]
		sid = str(pl.get("session_id") or "").strip()
		lines = str(pl.get("source_lines") or "").strip()
		if scope in ("source", "collection") and (not sid or not lines):
			sin_clave.append(p["id"])
			continue
		hash_ = body_hash(pl.get("content"))
		if scope == "source":
			key = (p["collection"], sid, lines, hash_)
		elif scope == "collection":
			key = (p["collection"], hash_)
		else:
			key = (hash_,)
		groups[key].append(p)

	by_source: Dict[tuple, set] = defaultdict(set)
	for key, items in groups.items():
		coll = items[0]["collection"]
		sid = str(items[0]["payload"].get("session_id") or "")
		lines = str(items[0]["payload"].get("source_lines") or "")
		by_source[(coll, sid, lines)].add(key[-1])

	entries: List[Dict[str, Any]] = []
	for key, items in groups.items():
		if len(items) < 2:
			continue
		refs = [p for p in items if p["id"] in referenced]
		pool = refs if refs else items
		routed_ok = 0
		if scope == "global" and route_resolver is not None:
			routed = [p for p in pool if route_resolver(p) == p["collection"]]
			if routed:
				pool = routed
			routed_ok = sum(1 for p in items if route_resolver(p) == p["collection"])
		ranked = sorted(pool, key=lambda p: (-score_point(p, weights)[0], -_f(p["payload"], "significance"), p["id"]))
		survivor = ranked[0]
		score, comps = score_point(survivor, weights)
		entries.append(
			{
				"collection": survivor["collection"],
				"session_id": str(survivor["payload"].get("session_id") or ""),
				"source_lines": str(survivor["payload"].get("source_lines") or ""),
				"body_hash": key[-1],
				"n": len(items),
				"colecciones": dict(Counter(p["collection"] for p in items)),
				"routed_ok": routed_ok,
				"survivor": {
					"id": survivor["id"],
					"score": score,
					"components": comps,
					"engine": survivor["payload"].get("engine"),
					"len": len(str(survivor["payload"].get("content") or "")),
				},
				"losers": [
					{
						"id": p["id"],
						"collection": p["collection"],
						"score": score_point(p, weights)[0],
						"engine": p["payload"].get("engine"),
						"len": len(str(p["payload"].get("content") or "")),
						"referenced": p["id"] in referenced,
					}
					for p in items
					if p["id"] != survivor["id"]
				],
				"protected": bool(refs),
			}
		)

	return {
		"generated_at": datetime.now(timezone.utc).isoformat(),
		"scope": scope,
		"weights": weights,
		"totals": {
			"points": len(points),
			"grupos_dup": len(entries),
			"borrados_planificados": sum(len(e["losers"]) for e in entries),
			"sin_clave": len(sin_clave),
			"fuentes_con_body_distinto": sum(1 for v in by_source.values() if len(v) > 1),
			"grupos_protegidos_por_referencia": sum(1 for e in entries if e["protected"]),
			"por_coleccion": dict(Counter(loser["collection"] for e in entries for loser in e["losers"])),
			"por_engine_borrados": dict(Counter(str(loser["engine"]) for e in entries for loser in e["losers"])),
			"survivores_por_coleccion": dict(Counter(e["collection"] for e in entries)),
			"survivores_con_ruta_ok": sum(1 for e in entries if e["routed_ok"] > 0),
		},
		"groups": entries,
	}


def scan_seals(root: Path, loser_ids: set) -> Dict[str, Any]:
	"""Sellos `ascended_point_id` de Memento que apuntan a perdedores (dangling)."""
	hits: List[Dict[str, str]] = []
	if not root.exists():
		return {"revisados": 0, "dangling": hits}
	reviewed = 0
	pattern = re.compile(r"^ascended_point_id:\s*(\S+)\s*$", re.MULTILINE)
	for md in root.rglob("*.md"):
		try:
			text = md.read_text(encoding="utf-8", errors="replace")
		except OSError:
			continue
		match = pattern.search(text)
		if not match:
			continue
		reviewed += 1
		if match.group(1) in loser_ids:
			hits.append({"file": str(md), "point_id": match.group(1)})
	return {"revisados": reviewed, "dangling": hits}


def fix_seals(hits: List[Dict[str, str]], remap: Dict[str, str]) -> int:
	"""Repunta los sellos dangling al superviviente (escritura atómica)."""
	fixed = 0
	for hit in hits:
		md = Path(hit["file"])
		new_id = remap.get(hit["point_id"])
		if not new_id:
			continue
		try:
			text = md.read_text(encoding="utf-8", errors="replace")
		except OSError:
			continue
		new_text = re.sub(
			rf"^(ascended_point_id:\s*){re.escape(hit['point_id'])}\s*$",
			rf"\g<1>{new_id}",
			text,
			count=1,
			flags=re.MULTILINE,
		)
		if new_text != text:
			tmp = md.with_suffix(md.suffix + ".tmp")
			tmp.write_text(new_text, encoding="utf-8")
			tmp.replace(md)
			fixed += 1
	return fixed


def deletions_by_collection(plan: Dict[str, Any], limit: int = 0) -> Dict[str, List[str]]:
	"""Ids a borrar agrupados por la colección DEL PERDEDOR (no la del supervivente).

	Bug detectado en el primer apply (2026-09-23): borrar con la colección del
	supervivente dejaba no-op los perdedores cruzados (work↔social).
	"""
	out: Dict[str, List[str]] = defaultdict(list)
	count = 0
	for entry in plan["groups"]:
		for loser in entry["losers"]:
			if limit and count >= limit:
				return out
			out[loser["collection"]].append(loser["id"])
			count += 1
	return out


def plan_dedup(points: List[tuple]) -> Dict[str, Any]:
	"""Planner M3 (contrato single-writer, commit f1441c7c): `points` = [(id, payload)].

	Agrupa SOLO candidatos `origin == "memento"` por (session_id, source_lines,
	body-hash); deja el de mayor significance (empate → id) y marca el resto en
	`to_delete`. No toca otros orígenes ni singletons. Es la vista estricta
	(P1-B original); el CLI usa `build_plan` (scopes/routing/referencias).
	"""
	groups: Dict[tuple, List[tuple]] = defaultdict(list)
	for point_id, payload in points:
		pl = dict(payload or {})
		if str(pl.get("origin") or "") != "memento":
			continue
		session_id = str(pl.get("session_id") or "").strip()
		lines = str(pl.get("source_lines") or "").strip()
		if not session_id or not lines:
			continue
		groups[(session_id, lines, body_hash(pl.get("content")))].append((str(point_id), pl))

	to_delete: List[str] = []
	detail: List[Dict[str, Any]] = []
	for key, items in groups.items():
		if len(items) < 2:
			continue
		ranked = sorted(items, key=lambda item: (-_f(item[1], "significance"), item[0]))
		keep, losers = ranked[0][0], [pid for pid, _pl in ranked[1:]]
		to_delete.extend(losers)
		detail.append({"session_id": key[0], "source_lines": key[1], "body_hash": key[2], "keep": keep, "delete": losers})
	return {"to_delete": to_delete, "groups": detail, "totals": {"grupos": len(detail), "borrados": len(to_delete)}}


def _make_route_resolver(root: Path):
	"""Resuelve la colección ENRUTADA de un punto leyendo su nota fuente (dual_route
	del annotate o category_score del refine). Cache por refine_ref."""
	cache: Dict[str, Optional[str]] = {}

	def resolve(point: Dict[str, Any]) -> Optional[str]:
		refine_ref = str(point["payload"].get("refine_ref") or "")
		if not refine_ref:
			return None
		if refine_ref in cache:
			return cache[refine_ref]
		route: Optional[str] = None
		md = root / refine_ref
		if md.exists():
			try:
				text = md.read_text(encoding="utf-8", errors="replace")
			except OSError:
				text = ""
			match = re.search(r"^dual_route:\s*[\"']?(\w+)", text, re.MULTILINE)
			if match and match.group(1) in ("work", "social"):
				route = f"{match.group(1)}_memories"
			else:
				score = re.search(r"^category_score:\s*([0-9.]+)", text, re.MULTILINE)
				if score:
					route = "work_memories" if float(score.group(1)) >= 0.5 else "social_memories"
		cache[refine_ref] = route
		return route

	return resolve


def _parse_weights(raw: str) -> Dict[str, float]:
	weights = dict(DEFAULT_WEIGHTS)
	for part in raw.split(","):
		part = part.strip()
		if not part:
			continue
		key, _, value = part.partition("=")
		key = key.strip()
		if key not in weights:
			raise SystemExit(f"[dedup] peso desconocido: '{key}' (usa {','.join(weights)})")
		weights[key] = float(value)
	return weights


def _load_points(memory_manager: Any) -> List[Dict[str, Any]]:
	points: List[Dict[str, Any]] = []
	for coll in ("work_memories", "social_memories"):
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(
				collection_name=coll, limit=1000, offset=offset, with_payload=True, with_vectors=False
			)
			for p in batch:
				points.append({"id": str(p.id), "collection": coll, "payload": dict(p.payload or {})})
			if offset is None:
				break
	return points


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--apply", action="store_true", help="Borra las réplicas (sin esto: dry-run).")
	parser.add_argument("--dry-run", action="store_true", help="Fuerza dry-run (default).")
	parser.add_argument(
		"--scope",
		choices=("source", "collection", "global"),
		default="source",
		help="Agrupación: source (RFC P1-B: coll+sesión+líneas+body) · collection (coll+body) · global (body, cruza colecciones).",
	)
	parser.add_argument("--report", type=Path, default=None, help="Escribe el plan JSON (y lo reutiliza si existe).")
	parser.add_argument("--weights", default="", help="Pesos del score: sig=1,cat=.5,len=.5,voz=.5,int=.3,eng=1")
	parser.add_argument("--limit", type=int, default=0, help="Máximo de borrados por pasada (0 = sin tope).")
	parser.add_argument("--fix-seals", action="store_true", help="Repunta sellos dangling al superviviente.")
	parser.add_argument("--no-snapshot", action="store_true", help="Omite el snapshot previo (no recomendado).")
	args = parser.parse_args()

	weights = _parse_weights(args.weights) if args.weights else dict(DEFAULT_WEIGHTS)

	from red_pill.memento import get_memento_root
	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	points = _load_points(mm)
	route_resolver = _make_route_resolver(Path(get_memento_root())) if args.scope == "global" else None
	plan = build_plan(points, weights, scope=args.scope, route_resolver=route_resolver)
	totals = plan["totals"]
	print(f"[dedup] scope={args.scope} · puntos={totals['points']} · grupos_dup={totals['grupos_dup']} · borrados_planificados={totals['borrados_planificados']}")
	print(f"[dedup] sin_clave={totals['sin_clave']} · fuentes_con_body_distinto={totals['fuentes_con_body_distinto']} · grupos_protegidos={totals['grupos_protegidos_por_referencia']}")
	print(f"[dedup] por_coleccion={totals['por_coleccion']} · por_engine={totals['por_engine_borrados']}")
	print(f"[dedup] superviventes={totals['survivores_por_coleccion']} · con_ruta_ok={totals['survivores_con_ruta_ok']}")

	loser_ids = {loser["id"] for e in plan["groups"] for loser in e["losers"]}
	remap = {loser["id"]: e["survivor"]["id"] for e in plan["groups"] for loser in e["losers"]}
	seals = scan_seals(Path(get_memento_root()), loser_ids)
	print(f"[dedup] sellos revisados={seals['revisados']} · dangling={len(seals['dangling'])}")
	if seals["dangling"]:
		for hit in seals["dangling"][:5]:
			print(f"         · {hit['file']} → {hit['point_id']}")

	if args.report:
		plan["seals_dangling"] = seals["dangling"]
		args.report.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
		print(f"[dedup] plan → {args.report}")

	if not args.apply:
		print("[dedup] dry-run: nada borrado (usa --apply).")
		return

	if not args.no_snapshot:
		for coll in ("work_memories", "social_memories"):
			try:
				snap = mm.client.create_snapshot(collection_name=coll)
				print(f"[dedup] snapshot {coll}: {snap.name}")
			except Exception as e:
				raise SystemExit(f"[dedup] no se pudo crear snapshot de {coll}: {e} — abortando (usa --no-snapshot para forzar)")

	deleted = 0
	for coll, ids in deletions_by_collection(plan, limit=args.limit).items():
		if not ids:
			continue
		mm.client.delete(collection_name=coll, points_selector=ids)
		deleted += len(ids)
	print(f"[dedup] borrados: {deleted}")

	if args.fix_seals and seals["dangling"]:
		fixed = fix_seals(seals["dangling"], remap)
		print(f"[dedup] sellos repuntados: {fixed}")

	for coll in ("work_memories", "social_memories"):
		print(f"[dedup] {coll}: {mm.client.get_collection(coll).points_count} puntos")


if __name__ == "__main__":
	main()
