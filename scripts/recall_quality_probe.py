#!/usr/bin/env python3
"""Prueba de CALIDAD de recuperación — ¿qué se siente al recordar?

No mide cobertura ni integridad: mide si al preguntar por algo real vuelve lo
que toca, en qué puesto y con qué texto. Usa el camino REAL de recuperación
(`search_and_reinforce` con `hybrid=True`, como el hot path), así que cuenta como
uso: cada consulta refuerza lo que devuelve (que es exactamente lo que hace un
turno de verdad).

MEM-011 F0 (2026-11-17): el informe separa **similitud** (`hit.score`) de
**utilidad** (`reinforcement_score`) — son campos distintos y las decisiones de
abstención van sobre la primera — y busca el detalle esperado sobre el `content`
**completo**, no sobre los primeros 110 chars: el caso `ciego-ayer` «fallaba» por
la ventana de medición, no por el recall.

Casos elegidos a mano con material del Búnker:
- un miembro que ayer era **ciego** (sesión con padre inexistente, ya restaurada);
- decisiones técnicas de sesiones distintas;
- memoria social (personal, no re-derivable del código);
- directivas (inmunes);
- un **control negativo**: algo que no debería estar en ninguna parte.

Uso: .venv/bin/python scripts/recall_quality_probe.py [--json PATH] [--semantic-only]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass

from red_pill.memory import MemoryManager


@dataclass(frozen=True)
class Case:
	name: str
	query: str
	collection: str
	expect: tuple[str, ...]  # subcadenas (minúsculas) que deberían aparecer en el top-k
	note: str
	kind: str = "must"  # must | known_limit | pending | negative | hard
	# Detalle que SOLO vive en una hoja (miembro), no en el resumen del hub: obliga a
	# bajar del hub a sus miembros. Es el caso que mide de verdad el problema de
	# resolución de MEM-011 (PC-SH-01: el descenso alcanza el detalle).
	deep_expect: tuple[str, ...] = ()


CASES: tuple[Case, ...] = (
	Case(
		name="ciego-ayer",
		query="el desk se siembra desde el germen y el instalador compara hashes",
		collection="work_memories",
		expect=("germen", "desk"),
		note="detalle fino dentro de una sesión de 302 miembros (ayer ciega)",
		kind="known_limit",
	),
	Case(
		name="decision-tecnica",
		query="checkpoint híbrido de tiempo en el frankenswarm",
		collection="work_memories",
		expect=("checkpoint",),
		note="hub restaurado de una sesión técnica",
	),
	Case(
		name="telegram",
		query="compactor de Telegram y gestión de registros",
		collection="work_memories",
		expect=("telegram",),
		note="decisión de otro día, otro tema",
	),
	Case(
		name="hoy-olvido",
		query="la rama no erosiona mientras tenga hojas, la escalera del olvido",
		collection="work_memories",
		expect=("olvido", "rama"),
		note="lo que hicimos ayer: no estará hasta que la crónica de esta noche lo destile",
		kind="pending",
	),
	Case(
		name="opencode-v2",
		query="opencode 1.19.4 app de escritorio frente a la v2",
		collection="work_memories",
		expect=("opencode",),
		note="detalle de entorno, no de decisión",
	),
	Case(
		name="social-cercania",
		query="la cercanía recuperada después de mi viaje y tu afecto",
		collection="social_memories",
		expect=("viaje", "cercan", "afecto"),
		note="memoria personal: no se puede re-derivar de ningún código",
	),
	Case(
		name="social-modelos",
		query="astronomía antigua y el cambio de modelo de IA",
		collection="social_memories",
		expect=("astronom", "modelo"),
		note="conversación social con tema mezclado",
	),
	Case(
		name="directiva-770",
		query="pacto 770 doble llave",
		collection="directive_memories",
		expect=("770", "pacto"),
		note="directiva inmune: no decae, no se olvida",
	),
	Case(
		name="detalle-en-la-hoja",
		query="política de merge del desk y límites de documentos KB",
		collection="work_memories",
		expect=("soft_limit_kb", "hard_limit_kb"),
		note="el hub dice KB; el criterio vigente (TOKENS y chars/token) solo vive en 2 de sus 302 hojas",
		kind="hard",
		deep_expect=("chars_per_token", "soft_limit_tokens"),
	),
	Case(
		name="detalle-sin-ancla",
		query="con qué criterio se mide el tamaño de los documentos del desk",
		collection="work_memories",
		expect=("soft_limit_kb", "hard_limit_kb"),
		note="misma sesión, pregunta sin ancla: falla por RANKING (el hub ni aparece), no por partición",
		kind="known_limit",
	),
	Case(
		name="negativo",
		query="receta de paella valenciana con marisco y azafrán",
		collection="work_memories",
		expect=(),
		note="control negativo: nada debería pasar de 0,70 de score",
		kind="negative",
	),
)


# Suelo de abstención de referencia (MEM-012). NO es política del kernel todavía:
# aquí solo se usa para decidir si un control negativo se quedó por debajo.
ABSTENTION_FLOOR = 0.30


def _snippet(text: str, n: int = 110) -> str:
	return " ".join(str(text or "").split())[:n]


def _matched_rank(rows: list, expect: tuple[str, ...], field: str) -> int | None:
	"""Primer puesto en cuyo texto (`field`) aparece alguna subcadena esperada."""
	if not expect:
		return None
	for row in rows:
		haystack = f"{row.get(field) or ''} {row.get('title') or ''}".lower()
		if any(e in haystack for e in expect):
			return row["rank"]
	return None


def _descend_for_detail(manager, case: Case, rows_full: list) -> dict:
	"""Baja de cada hub devuelto a sus miembros y busca el detalle ahí.

	Es el camino que el agente hace de verdad: recall → hub → `hub_members` /
	`traverse_thread`. Cada miembro se compara por `content` completo.
	"""
	from qdrant_client.http import models as qm

	scanned = 0
	for row in rows_full:
		if not row.get("id"):
			continue
		offset = None
		while True:
			points, offset = manager.client.scroll(
				collection_name=case.collection,
				limit=256,
				offset=offset,
				with_payload=["content"],
				with_vectors=False,
				scroll_filter=qm.Filter(must=[qm.FieldCondition(key="hub_id", match=qm.MatchValue(value=row["id"]))]),
			)
			for point in points:
				scanned += 1
				text = str((point.payload or {}).get("content") or "").lower()
				if any(e in text for e in case.deep_expect):
					return {"found": True, "members_scanned": scanned, "hub": row["id"], "via": "hub_members"}
			if offset is None:
				break
	return {"found": False, "members_scanned": scanned, "via": "hub_members"}


def run(case: Case, hybrid: bool = True) -> dict:
	manager = MemoryManager()
	started = time.perf_counter()
	hits = manager.search_and_reinforce(case.collection, case.query, limit=3, caller="quality_probe", hybrid=hybrid)
	elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
	rows = []
	for rank, hit in enumerate(hits, start=1):
		payload = getattr(hit, "payload", {}) or {}
		rows.append(
			{
				"rank": rank,
				"id": str(getattr(hit, "id", "")),
				# Similitud del hit (relevancia) vs utilidad bayesiana (decaimiento).
				"similarity": round(float(getattr(hit, "score", 0.0) or 0.0), 3),
				"score": round(float(payload.get("reinforcement_score") or 0), 3),
				"session": str(payload.get("session_id") or "")[:28],
				"node": str(payload.get("node_type") or payload.get("lazarus_phase") or "?"),
				"title": payload.get("hub_title"),
				"snippet": _snippet(payload.get("content")),
				"content_len": len(str(payload.get("content") or "")),
			}
		)
	# El detalle se busca sobre el CONTENIDO COMPLETO (no sobre el snippet de 110).
	full_rows = [{**row, "content": str((getattr(hit, "payload", {}) or {}).get("content") or "")} for row, hit in zip(rows, hits)]
	first_hit = _matched_rank(rows, case.expect, "snippet")
	detail_hit = _matched_rank(full_rows, case.expect, "content")
	rows = rows[:3]
	max_score = max((r["score"] for r in rows), default=0.0)
	max_similarity = max((r["similarity"] for r in rows), default=0.0)

	deep = _descend_for_detail(manager, case, rows_full=full_rows) if case.deep_expect else {}
	if case.kind == "negative":
		passed = max_similarity <= ABSTENTION_FLOOR
	elif case.kind == "hard":
		# El detalle no está en el resumen: tiene que aparecer al bajar a las hojas.
		passed = bool(deep.get("found"))
	else:
		passed = bool(detail_hit)
	return {
		"name": case.name,
		"query": case.query,
		"collection": case.collection,
		"note": case.note,
		"expect": list(case.expect),
		"ms": elapsed_ms,
		"results": rows,
		"hit": passed,
		"snippet_hit_rank": first_hit,
		"detail_hit_rank": detail_hit,
		"kind": case.kind,
		"max_score": max_score,
		"max_similarity": max_similarity,
		"deep": deep,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--json", metavar="PATH")
	ap.add_argument(
		"--semantic-only",
		action="store_true",
		help="no pide recall híbrido (por defecto usa el camino real del hot path)",
	)
	args = ap.parse_args()

	report = []
	for case in CASES:
		r = run(case, hybrid=not args.semantic_only)
		report.append(r)
		mark = {
			"must": "OK " if r["hit"] else "NO ",
			"known_limit": "LIM",
			"pending": "PEN",
			"negative": "OK " if r["hit"] else "NO ",
			"hard": "OK " if r["hit"] else "NO ",
		}[case.kind]
		if case.kind in ("must", "negative", "hard") and r["hit"]:
			mark = "OK "
		if case.kind in ("must", "negative", "hard") and not r["hit"]:
			mark = "NO "
		rank = f"detalle en puesto {r['detail_hit_rank']} (snippet: {r['snippet_hit_rank']})" if r["detail_hit_rank"] else "detalle sin acierto"
		print(f"\n[{mark}] {case.name} · {r['ms']} ms · {rank}")
		print(f"   pregunta: {case.query}")
		print(f"   ({case.note})")
		if case.deep_expect:
			deep = r.get("deep") or {}
			print(
				f"   detalle en el resumen del hub: {'sí' if r['detail_hit_rank'] else 'NO'}"
				f" · al bajar a las hojas: {'sí' if deep.get('found') else 'NO'}"
				f" ({deep.get('members_scanned', 0)} miembros recorridos)"
			)
		for row in r["results"]:
			tag = "hub" if row["node"] == "synthesis_hub" else row["node"]
			print(f"     {row['rank']}. sim={row['similarity']:.3f} util={row['score']:.2f} len={row['content_len']:<5} {tag:<16} {row['snippet']}")
		if not r["results"]:
			print("     (nada)")

	must = [r for r in report if r["kind"] in ("must", "negative", "hard")]
	hits = sum(1 for r in must if r["hit"])
	limits = [r for r in report if r["kind"] == "known_limit"]
	pending = [r for r in report if r["kind"] == "pending"]
	print(
		f"\n== obligatorios: {hits}/{len(must)} (detalle en content completo, similitud para el negativo)"
		f" · límites conocidos: {len(limits)} · pendientes de crónica: {len(pending)} =="
	)
	if args.json:
		with open(args.json, "w", encoding="utf-8") as fh:
			json.dump(report, fh, indent=1, ensure_ascii=False)
		print(f"informe: {args.json}")
	return 0 if hits == len(must) else 1


if __name__ == "__main__":
	sys.exit(main())
