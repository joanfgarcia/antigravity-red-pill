#!/usr/bin/env python3
"""Prueba de CALIDAD de recuperación — ¿qué se siente al recordar?

No mide cobertura ni integridad: mide si al preguntar por algo real vuelve lo
que toca, en qué puesto y con qué texto. Usa el camino REAL de recuperación
(`search_and_reinforce`), así que cuenta como uso: cada consulta refuerza lo que
devuelve (que es exactamente lo que hace un turno de verdad).

Casos elegidos a mano con material del Búnker:
- un miembro que ayer era **ciego** (sesión con padre inexistente, ya restaurada);
- decisiones técnicas de sesiones distintas;
- memoria social (personal, no re-derivable del código);
- directivas (inmunes);
- un **control negativo**: algo que no debería estar en ninguna parte.

Uso: .venv/bin/python scripts/recall_quality_probe.py [--json PATH]
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
	kind: str = "must"  # must | known_limit | pending


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
		name="negativo",
		query="receta de paella valenciana con marisco y azafrán",
		collection="work_memories",
		expect=(),
		note="control negativo: nada debería pasar de 0,70 de score",
		kind="negative",
	),
)


def _snippet(text: str, n: int = 110) -> str:
	return " ".join(str(text or "").split())[:n]


def run(case: Case) -> dict:
	manager = MemoryManager()
	started = time.perf_counter()
	hits = manager.search_and_reinforce(case.collection, case.query, limit=3, caller="quality_probe")
	elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
	rows = []
	for rank, hit in enumerate(hits, start=1):
		payload = getattr(hit, "payload", {}) or {}
		rows.append(
			{
				"rank": rank,
				"score": round(float(payload.get("reinforcement_score") or 0), 3),
				"session": str(payload.get("session_id") or "")[:28],
				"node": str(payload.get("node_type") or payload.get("lazarus_phase") or "?"),
				"title": payload.get("hub_title"),
				"snippet": _snippet(payload.get("content")),
			}
		)
	rows = rows[:3]
	first_hit = next((r["rank"] for r in rows if any(e in (r["snippet"] + " " + str(r["title"] or "")).lower() for e in case.expect)), None)
	max_score = max((r["score"] for r in rows), default=0.0)
	return {
		"name": case.name,
		"query": case.query,
		"collection": case.collection,
		"note": case.note,
		"expect": list(case.expect),
		"ms": elapsed_ms,
		"results": rows,
		"hit": (max_score < 0.70 and case.kind == "negative") or bool(first_hit),
		"first_hit_rank": first_hit,
		"kind": case.kind,
		"max_score": max_score,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--json", metavar="PATH")
	args = ap.parse_args()

	report = []
	for case in CASES:
		r = run(case)
		report.append(r)
		mark = {"must": "OK " if r["hit"] else "NO ", "known_limit": "LIM", "pending": "PEN", "negative": "OK " if r["hit"] else "NO "}[case.kind]
		if case.kind in ("must", "negative") and r["hit"]:
			mark = "OK "
		if case.kind in ("must", "negative") and not r["hit"]:
			mark = "NO "
		rank = f"puesto {r['first_hit_rank']}" if r["first_hit_rank"] else "sin acierto"
		print(f"\n[{mark}] {case.name} · {r['ms']} ms · {rank}")
		print(f"   pregunta: {case.query}")
		print(f"   ({case.note})")
		for row in r["results"]:
			tag = "hub" if row["node"] == "synthesis_hub" else row["node"]
			print(f"     {row['rank']}. [{row['score']:.2f}] {tag:<16} {row['snippet']}")
		if not r["results"]:
			print("     (nada)")

	must = [r for r in report if r["kind"] in ("must", "negative")]
	hits = sum(1 for r in must if r["hit"])
	limits = [r for r in report if r["kind"] == "known_limit"]
	pending = [r for r in report if r["kind"] == "pending"]
	print(f"\n== obligatorios: {hits}/{len(must)} · límites conocidos: {len(limits)} · pendientes de crónica: {len(pending)} ==")
	if args.json:
		with open(args.json, "w", encoding="utf-8") as fh:
			json.dump(report, fh, indent=1, ensure_ascii=False)
		print(f"informe: {args.json}")
	return 0 if hits == len(must) else 1


if __name__ == "__main__":
	sys.exit(main())
