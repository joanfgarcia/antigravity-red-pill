#!/usr/bin/env python3
"""bench_annotate.py — banco reproducible de annotate (NB-001 F4, P6).

QUÉ ES
	Mide el coste de la etapa `annotate` (MEM-006) sobre un fixture SINTÉTICO y
	FIJO de fragmentos, sin datos privados y sin depender del árbol Memento real:
	cualquier puesto lo corre igual y las comparaciones son justas.

	El fixture se anota con el MISMO pipeline de producción
	(`red_pill.memento.agentic.annotate_session`): extracción work+social por
	split, dedup P1-A, scoring dual y gate de rutas. El transporte se envuelve
	para contar llamadas, cronometrarlas y detectar respuestas truncadas o con
	JSON inválido — así el banco mide lo que de verdad cuesta y lo que el modelo
	devuelve, sin reimplementar el pipeline.

	BASELINE (PLAN-NB-001 §0 / D-NB-04): **2 llamadas por split** — la extracción
	lanza UNA llamada de work y UNA de social por cada split (`_extract` en
	`annotation_phases.py`). El banco la imprime como `extract_por_fragmento`.

USO
	PYTHONPATH=src python scripts/bench_annotate.py --dry-run        # CI: sin LLM
	PYTHONPATH=src python scripts/bench_annotate.py --repetitions 3  # mide de verdad
	Salida: <out>/ANNOTATE_BENCH.jsonl (una línea por corrida) + <out>/ANNOTATE_BENCH.md.

ESQUEMA JSONL (v1) — un registro por corrida:
	bench                  "annotate" (fijo)
	schema_version         1
	ts                     ISO-8601 UTC de la corrida
	dry_run                bool — True = transporte falso, sin LLM (valida arnés+fixture)
	fixture_hash           "sha256:<hex>" — hash canónico del fixture (estable entre corridas)
	fixture_fragments      int — nº de fragmentos del fixture
	repetition             int — índice de la corrida (1..N)
	llamadas               int — nº total de llamadas al transporte
	llamadas_extract       int — llamadas de extracción (work+social)
	llamadas_score         int — llamadas de scoring dual
	llamadas_rewrite       int — llamadas de re-escritura de voz
	llamadas_por_fragmento float — llamadas / fragmentos
	extract_por_fragmento  float — llamadas_extract / fragmentos (baseline = 2.0)
	notas_total            int — notas materializadas
	notas_por_fragmento    [int] — notas por fragmento (por NNN del fichero)
	rutas                  {work, social, none} — distribución del gate
	truncados              int — respuestas con DEGRADED_MARKER (prompt recortado)
	json_invalido          int — respuestas sin array JSON válido
	segundos_total         float — segundos de TODAS las llamadas
	segundos_por_fragmento [float] — segundos de las 2 llamadas de extracción por fragmento

Nota: `fragmento` == `split` == `unidad` (un `memento/NNN-mensajes-*.md`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
# Importa el checkout bajo prueba, no el `red_pill` instalado en el venv
# (el editable apunta al checkout principal: un worktree probaría `main`).
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from red_pill.memento.agentic import (  # noqa: E402
	ANNOTATE_COMBINED_SYSTEM,
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	annotate_session,
	http_transport,
)
from red_pill.memento.agentic import runtime as agentic_runtime  # noqa: E402

BENCH_ID = "annotate"
SCHEMA_VERSION = 1
# Baseline de la etapa (PLAN-NB-001): 1 llamada de work + 1 de social por split.
BASELINE_EXTRACT_PER_SPLIT = 2

SESSION_DIR = "2026-11/bench/bench-session"
SESSION_ID = "bench:s1"
SOURCE = "bench"


# ── Fixture FIJO (sintético, reproducible) ──────────────────────────────────────
# Fragmentos de diálogo inventados, sin datos privados. Cada fragmento es un
# split: un `memento/NNN-mensajes-<rango>.md`. El hash canónico de esta lista es
# la identidad del banco (fixture_hash) y es estable entre corridas.
FIXTURE_FRAGMENTS: List[Dict[str, str]] = [
	{
		"rango": "0001-0040",
		"content": "## 2026-11-08T22:10:00Z — Usuario\nHe revisado el fallo del daemon: pierde VRAM tras tres prefill largos seguidos.\n\n## 2026-11-08T22:10:40Z — Asistente\nConfirmado, el leak viene del pool VMM; lo he acotado con un cap de 16384 de contexto en el camino python.",
	},
	{
		"rango": "0041-0080",
		"content": "## 2026-11-08T22:14:00Z — Usuario\nQuédate con esa cota, y añade una guarda que aborte si el wheel no trae CUDA.\n\n## 2026-11-08T22:15:10Z — Asistente\nHecho: la guarda mira llama_supports_gpu_offload y aborta con aviso si iría a CPU.",
	},
	{
		"rango": "0081-0120",
		"content": "## 2026-11-08T22:30:00Z — Usuario\nHoy me he acordado de cuando montábamos los servidores en la terraza del piso viejo.\n\n## 2026-11-08T22:31:00Z — Asistente\nEsos atardeceres con el ruido de los ventiladores de fondo eran otra cosa.",
	},
	{
		"rango": "0121-0160",
		"content": "## 2026-11-09T09:02:00Z — Usuario\nEl nocturnal se quedó a medias anoche: la fase de hubs tardó cuarenta y seis minutos.\n\n## 2026-11-09T09:03:20Z — Asistente\nLo he visto en el journal; la síntesis de hubs domina el sueño, no las diez fases.",
	},
	{
		"rango": "0161-0200",
		"content": "## 2026-11-09T09:20:00Z — Usuario\nAnota una decisión: seguimos con SQLite, el volumen no justifica aún Postgres.\n\n## 2026-11-09T09:21:00Z — Asistente\nDe acuerdo, lo dejo sellado en el registro de decisiones con su motivo.",
	},
	{
		"rango": "0201-0240",
		"content": "## 2026-11-09T19:05:00Z — Usuario\nEsta tarde he salido a correr por el paseo marítimo y me he despejado del todo.\n\n## 2026-11-09T19:06:00Z — Asistente\nBien hecho, a veces el cuerpo necesita su turno para que la cabeza vuelva fresca.",
	},
	{
		"rango": "0241-0280",
		"content": "## 2026-11-10T01:10:00Z — Usuario\nEl reuso por unidad en annotate ya está: solo se re-extrae la cola que creció.\n\n## 2026-11-10T01:11:30Z — Asistente\nY la unidad marcada degraded nunca se reusa, que era el caso que nos faltaba cubrir.",
	},
	{
		"rango": "0281-0320",
		"content": "## 2026-11-10T01:40:00Z — Usuario\nMañana toca el banco de annotate para poder medir las dos llamadas por split.\n\n## 2026-11-10T01:41:00Z — Asistente\nPreparado: fixture fijo, N repeticiones y dry-run para el CI sin tocar el modelo.",
	},
]

# Léxico disjunto por fragmento (el dedup P1-A compara tokens de ≥4 letras): cada
# fragmento necesita un vocabulario propio para que sus notas no se colapsen.
DRY_WORDS = ["arranque", "bitácora", "cerrojo", "dintel", "esclusa", "fragua", "galería", "herraje"]


def fixture_canonical() -> str:
	"""Representación canónica del fixture (serialización estable para el hash)."""
	return json.dumps(FIXTURE_FRAGMENTS, ensure_ascii=False, sort_keys=True)


def fixture_hash() -> str:
	"""Hash de identidad del fixture — estable entre corridas (criterio P6.2)."""
	return "sha256:" + hashlib.sha256(fixture_canonical().encode("utf-8")).hexdigest()


# ── Transporte contador (mide sin reimplementar el pipeline) ────────────────────


def _dry_scores(i: int) -> tuple[float, float]:
	"""Puntuación determinista por índice de nota: mezcla work/social/none."""
	if i % 3 == 0:
		return 0.9, 0.2  # work
	if i % 3 == 1:
		return 0.2, 0.8  # social
	return 0.55, 0.5  # margen < dead_zone → none


class CountingTransport:
	"""Envuelve el transporte real (o genera respuestas falsas en dry-run) contando.

	Clasifica las llamadas por system prompt (extract work / extract social /
	extract combined / score / rewrite) y, para las de extracción, las atribuye al
	fragmento por el orden determinista del bucle (work+social por split en baseline;
	UNA llamada combinada por split con `--single-call`). Detecta truncado
	(DEGRADED_MARKER) y JSON inválido (sin array parseable).
	"""

	def __init__(self, dry_run: bool, extract_per_split: int = BASELINE_EXTRACT_PER_SPLIT) -> None:
		self._dry_run = dry_run
		self._extract_per_split = extract_per_split
		self._extract_seq = 0
		self.calls = 0
		self.extract_work = 0
		self.extract_social = 0
		self.extract_combined = 0
		self.score = 0
		self.rewrite = 0
		self.truncated = 0
		self.invalid_json = 0
		self.total_s = 0.0
		self.extract_s = [0.0] * len(FIXTURE_FRAGMENTS)

	def __call__(self, system: str, user: str, max_tokens: int) -> str:
		is_extract = system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM, ANNOTATE_COMBINED_SYSTEM)
		fragment = -1
		if is_extract:
			fragment = self._extract_seq // self._extract_per_split
			self._extract_seq += 1
		start = time.perf_counter()
		raw = self._fake(system, user, max_tokens, fragment) if self._dry_run else http_transport(system, user, max_tokens)
		elapsed = time.perf_counter() - start
		self.calls += 1
		self.total_s += elapsed
		if agentic_runtime.is_degraded(raw):
			self.truncated += 1
		if agentic_runtime._extract_json_array(raw) is None:
			self.invalid_json += 1
		if is_extract:
			if 0 <= fragment < len(self.extract_s):
				self.extract_s[fragment] += elapsed
			if system == ANNOTATE_WORK_SYSTEM:
				self.extract_work += 1
			elif system == ANNOTATE_SOCIAL_SYSTEM:
				self.extract_social += 1
			else:
				self.extract_combined += 1
		elif system == DUAL_SCORE_SYSTEM:
			self.score += 1
		else:
			self.rewrite += 1
		return raw

	def _fake(self, system: str, user: str, max_tokens: int, fragment: int) -> str:
		"""Respuestas deterministas (dry-run): valida arnés + fixture sin LLM."""
		if system == ANNOTATE_COMBINED_SYSTEM:
			word = DRY_WORDS[fragment] if 0 <= fragment < len(DRY_WORDS) else f"fragmento{fragment}"
			return json.dumps(
				[
					{
						"scope": "work",
						"title": f"Idea {fragment + 1}",
						"text": f"{word} {word}ado",
						"significance": 0.75,
						"emotion": "cyan",
						"intensity": 0.5,
						"theme": f"tema-{fragment}",
						"relics": [],
					}
				],
				ensure_ascii=False,
			)
		if system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM):
			if system == ANNOTATE_SOCIAL_SYSTEM:
				return "[]"
			word = DRY_WORDS[fragment] if 0 <= fragment < len(DRY_WORDS) else f"fragmento{fragment}"
			return json.dumps(
				[
					{
						"title": f"Idea {fragment + 1}",
						"text": f"{word} {word}ado",
						"significance": 0.75,
						"emotion": "cyan",
						"intensity": 0.5,
						"theme": f"tema-{fragment}",
						"relics": [],
					}
				],
				ensure_ascii=False,
			)
		if system == DUAL_SCORE_SYSTEM:
			idxs = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.M)]
			return json.dumps([{"i": i, "work_score": _dry_scores(i)[0], "social_score": _dry_scores(i)[1]} for i in idxs], ensure_ascii=False)
		# rewrite (no se alcanza con voice_rewrite OFF, pero el transporte queda completo)
		idxs = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.M)]
		return json.dumps([{"i": i, "text": "reescrito"} for i in idxs], ensure_ascii=False)


# ── Runtime determinista para dry-run ───────────────────────────────────────────


def _dry_run_context(single_call: bool = False) -> ExitStack:
	"""Fija runtime+flags para que el dry-run sea reproducible en cualquier puesto."""
	import red_pill.config as cfg

	patches = [
		mock.patch.object(agentic_runtime, "engine_id", lambda: "bench-engine"),
		mock.patch.object(agentic_runtime, "served_engine", lambda: "bench-engine"),
		mock.patch.object(agentic_runtime, "model_trust", lambda: "full"),
		mock.patch.object(agentic_runtime, "annotate_prompt_version", lambda: "bench-pv-1"),
		mock.patch.object(agentic_runtime, "fragment_view_settings", lambda: ("raw", "Operador", "Agente")),
		mock.patch.object(agentic_runtime, "annotate_scopes", lambda: ("", "")),
		mock.patch.object(agentic_runtime, "annotate_prompt_set", lambda: ""),
		mock.patch.object(agentic_runtime, "voice_v2_enabled", lambda: False),
		mock.patch.object(cfg, "MEMENTO_ANNOTATE_VOICE_REWRITE", False, create=True),
		mock.patch.object(cfg, "MEMENTO_ANNOTATE_POST_REWRITE_DEDUP", False, create=True),
		mock.patch.object(cfg, "MEMENTO_ANNOTATE_REUSE_ENABLED", False, create=True),
		mock.patch.object(cfg, "MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED", single_call, create=True),
		mock.patch.object(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK", 0.6, create=True),
		mock.patch.object(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL", 0.5, create=True),
		mock.patch.object(cfg, "MEMENTO_ANNOTATE_DEAD_ZONE", 0.05, create=True),
	]
	stack = ExitStack()
	for patch in patches:
		stack.enter_context(patch)
	return stack


# ── Ejecución de una corrida ────────────────────────────────────────────────────


def _build_session_tree(root: Path) -> None:
	memento_dir = root / SESSION_DIR / "memento"
	memento_dir.mkdir(parents=True, exist_ok=True)
	for i, fragment in enumerate(FIXTURE_FRAGMENTS, start=1):
		name = f"{i:03d}-mensajes-{fragment['rango']}.md"
		(memento_dir / name).write_text(f"> [!ref] memento/{name}#l1-40\n{fragment['content']}\n", encoding="utf-8")


def _collect(annotate_dir: Path) -> tuple[int, List[int], Dict[str, int]]:
	"""Notas totales, notas por fragmento (por NNN) y distribución de rutas."""
	notes = sorted(annotate_dir.glob("[0-9][0-9][0-9]-*.md"))
	per_fragment = [0] * len(FIXTURE_FRAGMENTS)
	for note in notes:
		try:
			nnn = int(note.name[:3])
		except ValueError:
			continue
		idx = nnn - 1
		if 0 <= idx < len(per_fragment):
			per_fragment[idx] += 1
	meta = json.loads((annotate_dir / "_meta.json").read_text(encoding="utf-8"))
	routes = meta.get("routes") or {}
	return len(notes), per_fragment, {
		"work": int(routes.get("work") or 0),
		"social": int(routes.get("social") or 0),
		"none": int(routes.get("none") or 0),
	}


def run_once(dry_run: bool, repetition: int, single_call: bool = False) -> Dict[str, Any]:
	"""Una corrida del banco: anota el fixture completo y devuelve sus métricas."""
	extract_per_split = 1 if single_call else BASELINE_EXTRACT_PER_SPLIT
	transport = CountingTransport(dry_run, extract_per_split)
	with tempfile.TemporaryDirectory(prefix="bench_annotate_") as tmp:
		root = Path(tmp)
		_build_session_tree(root)
		ctx = _dry_run_context(single_call) if dry_run else _single_call_context(single_call)
		with ctx:
			annotate_session(root, SESSION_DIR, SESSION_ID, SOURCE, transport)
		notas_total, notas_por_fragmento, rutas = _collect(root / SESSION_DIR / "annotate")
	fragments = len(FIXTURE_FRAGMENTS)
	extract = transport.extract_work + transport.extract_social + transport.extract_combined
	return {
		"bench": BENCH_ID,
		"schema_version": SCHEMA_VERSION,
		"ts": datetime.now(timezone.utc).isoformat(),
		"dry_run": dry_run,
		"fixture_hash": fixture_hash(),
		"fixture_fragments": fragments,
		"repetition": repetition,
		"llamadas": transport.calls,
		"llamadas_extract": extract,
		"llamadas_score": transport.score,
		"llamadas_rewrite": transport.rewrite,
		"llamadas_por_fragmento": round(transport.calls / fragments, 3),
		"extract_por_fragmento": round(extract / fragments, 3),
		"notas_total": notas_total,
		"notas_por_fragmento": notas_por_fragmento,
		"rutas": rutas,
		"truncados": transport.truncated,
		"json_invalido": transport.invalid_json,
		"segundos_total": round(transport.total_s, 3),
		"segundos_por_fragmento": [round(s, 3) for s in transport.extract_s],
	}


def _single_call_context(single_call: bool) -> ExitStack:
	"""Activa el flag F4-fusión para la corrida real (sin LLM falso)."""
	if not single_call:
		return ExitStack()
	import red_pill.config as cfg

	stack = ExitStack()
	stack.enter_context(mock.patch.object(cfg, "MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED", True, create=True))
	return stack


# ── Salida (JSONL + resumen MD) ─────────────────────────────────────────────────


def _write_jsonl(out_dir: Path, records: List[Dict[str, Any]]) -> None:
	out_dir.mkdir(parents=True, exist_ok=True)
	path = out_dir / "ANNOTATE_BENCH.jsonl"
	with path.open("w", encoding="utf-8") as fh:
		for record in records:
			fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_md(out_dir: Path, records: List[Dict[str, Any]], dry_run: bool, repetitions: int, single_call: bool = False) -> None:
	first = records[0]
	routes = first["rutas"]
	rows = []
	for record in records:
		rows.append(
			"| {rep} | {calls} | {extract} | {score} | {rewrite} | {notas} | {work} | {social} | {none} | {trunc} | {invalid} | {secs} |".format(
				rep=record["repetition"],
				calls=record["llamadas"],
				extract=record["llamadas_extract"],
				score=record["llamadas_score"],
				rewrite=record["llamadas_rewrite"],
				notas=record["notas_total"],
				work=routes["work"],
				social=routes["social"],
				none=routes["none"],
				trunc=record["truncados"],
				invalid=record["json_invalido"],
				secs=f"{record['segundos_total']:.2f}",
			)
		)
	mode = "dry-run (sin LLM — valida arnés + fixture)" if dry_run else "real (LLM local)"
	baseline = "1 llamada combinada por split (work+social fusionados)" if single_call else "2 llamadas por split (work + social en la extracción)"
	md = "\n".join(
		[
			"# ANNOTATE BENCH — banco reproducible de annotate (NB-001 F4/P6)",
			"",
			f"- **Fecha**: {first['ts']}",
			f"- **Fixture**: `{first['fixture_hash']}` — {first['fixture_fragments']} fragmentos sintéticos y fijos",
			f"- **Modo**: {mode}",
			f"- **Baseline**: **{baseline}**",
			"",
			"Un `fragmento` == `split` == `unidad` (un `memento/NNN-mensajes-*.md`). El banco",
			"mide la etapa annotate real (extract → dedup → score → gate), envolviendo el",
			"transporte para contar llamadas, cronometrarlas y detectar respuestas truncadas",
			"o con JSON inválido.",
			"",
			"## Esquema JSONL (v1)",
			"",
			"| campo | tipo | descripción |",
			"| :--- | :--- | :--- |",
			"| `bench` | str | `\"annotate\"` (fijo) |",
			"| `schema_version` | int | versión del esquema |",
			"| `ts` | str | ISO-8601 UTC de la corrida |",
			"| `dry_run` | bool | transporte falso sin LLM |",
			"| `fixture_hash` | str | hash canónico del fixture (estable) |",
			"| `fixture_fragments` | int | nº de fragmentos |",
			"| `repetition` | int | índice de corrida (1..N) |",
			"| `llamadas` | int | nº total de llamadas |",
			"| `llamadas_extract` | int | llamadas de extracción (work+social) |",
			"| `llamadas_score` | int | llamadas de scoring dual |",
			"| `llamadas_rewrite` | int | llamadas de re-escritura de voz |",
			"| `llamadas_por_fragmento` | float | `llamadas / fragmentos` |",
			"| `extract_por_fragmento` | float | `llamadas_extract / fragmentos` (**baseline = 2.0**) |",
			"| `notas_total` | int | notas materializadas |",
			"| `notas_por_fragmento` | [int] | notas por fragmento (por NNN) |",
			"| `rutas` | {work, social, none} | distribución del gate |",
			"| `truncados` | int | respuestas con `DEGRADED_MARKER` |",
			"| `json_invalido` | int | respuestas sin array JSON válido |",
			"| `segundos_total` | float | segundos de todas las llamadas |",
			"| `segundos_por_fragmento` | [float] | segundos de las 2 llamadas de extracción por fragmento |",
			"",
			f"## Corridas ({repetitions})",
			"",
			"| rep | llamadas | extract | score | rewrite | notas | work | social | none | trunc | JSON inválido | s total |",
			"| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
			*rows,
			"",
			"## Cómo medir el baseline real",
			"",
			"```",
			"PYTHONPATH=src python scripts/bench_annotate.py --repetitions 3",
			"```",
			"",
			"El `dry-run` (por defecto en CI) no llama al modelo: valida el arnés y el",
			"fixture, y ya imprime el baseline de 2 llamadas por split (es una propiedad",
			"del pipeline, no del modelo).",
			"",
		]
	)
	out_dir.mkdir(parents=True, exist_ok=True)
	(out_dir / "ANNOTATE_BENCH.md").write_text(md, encoding="utf-8")


# ── CLI ─────────────────────────────────────────────────────────────────────────


def main() -> int:
	ap = argparse.ArgumentParser(description="Banco reproducible de annotate (NB-001 F4/P6)")
	ap.add_argument("--dry-run", action="store_true", help="Transporte falso, sin LLM: valida arnés + fixture (para CI).")
	ap.add_argument("--repetitions", type=int, default=1, help="Nº de corridas sobre el fixture (default 1).")
	ap.add_argument("--single-call", action="store_true", help="F4-fusión ON: UNA llamada combinada (work+social) por split en vez de dos.")
	ap.add_argument("--out", default=str(REPO / "docs" / "BENCHMARKS"), help="Directorio de salida (default: docs/BENCHMARKS).")
	args = ap.parse_args()

	if args.repetitions < 1:
		print("--repetitions debe ser >= 1", file=sys.stderr)
		return 2

	records: List[Dict[str, Any]] = []
	for repetition in range(1, args.repetitions + 1):
		record = run_once(args.dry_run, repetition, single_call=args.single_call)
		records.append(record)
		print(
			f"[bench] corrida {repetition}/{args.repetitions}: "
			f"llamadas={record['llamadas']} extract={record['llamadas_extract']} score={record['llamadas_score']} "
			f"notas={record['notas_total']} rutas={record['rutas']} truncados={record['truncados']} "
			f"json_invalido={record['json_invalido']} s={record['segundos_total']:.3f}",
			flush=True,
		)

	# Baseline: una propiedad del pipeline (1 llamada work + 1 social por split; o
	# 1 combinada por split con --single-call).
	if args.single_call:
		print("[baseline] extract: 1 llamada por split (combinada work+social)", flush=True)
	else:
		print(f"[baseline] extract: {BASELINE_EXTRACT_PER_SPLIT} llamadas por split (work + social)", flush=True)
	print(f"[fixture] sha256={fixture_hash()} ({len(FIXTURE_FRAGMENTS)} fragmentos)", flush=True)

	out_dir = Path(args.out)
	_write_jsonl(out_dir, records)
	_write_md(out_dir, records, args.dry_run, args.repetitions, single_call=args.single_call)
	print(f"[out] {out_dir / 'ANNOTATE_BENCH.jsonl'}", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main())
