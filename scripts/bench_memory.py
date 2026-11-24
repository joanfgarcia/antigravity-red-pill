#!/usr/bin/env python3
"""Batería de memoria: ¿la capa de memoria de Dokimé bate a un agente desnudo?

Diseño
------
Cada trial siembra códigos ÚNICOS en dos superficies:
  - Bünker (`work_memories` de Qdrant), que Dokimé recibe por el RAG por turno.
  - Memoria de workspace (`<cwd>/.red-pill/memory/`), que cualquier brazo con
    `bash` puede leer si se le ocurre mirar.
Así el test no es "solo Dokimé puede saberlo": todos pueden, pero Dokimé lo
recibe sin buscar. Se mide acierto, tiempo, tool calls y timeouts.

Brazos
------
  minion      bucle del minion, solo `run_bash` (sin capa red-pill)
  pi-bare     pi sin extensiones / MCP / skills / context files
  dokime      pi con extensiones red-pill (RAG por turno, umbral 0.7)
  dokime55    ídem con RED_PILL_SCORE_THRESHOLD=0.55 (coste del umbral)

Uso
---
  python scripts/bench_memory.py --only m1,m2 --trials 1
  python scripts/bench_memory.py --arms minion,pi-bare,dokime --trials 3
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

BOX = "dokime"
GUEST = "/srv/dokime/membench"
RUNNER = "/srv/dokime/bench_minion_runner.py"
OUT_DIR = Path(__file__).resolve().parent.parent / "scratch" / "benchmarks"

SEED_SOURCE = "bench_memory"


# ── tareas ────────────────────────────────────────────────────────────────


def build_tasks(codes: dict[str, str]) -> list[dict]:
	"""Las 6 tareas de la batería, con los códigos del trial ya inyectados."""
	cal, old, inv = codes["cal"], codes["old"], codes["inv"]
	return [
		{
			"id": "m1",
			"category": "recall_literal",
			"prompt": "¿Cuál es el código de calibración del banco de pruebas? Responde sólo el código.",
			"kind": "code",
			"expect": cal,
			"forbid": [],
		},
		{
			"id": "m2",
			"category": "recall_parafrase",
			"prompt": "¿Qué identificador usa el banco de pruebas para calibrarse? Responde sólo el identificador.",
			"kind": "code",
			"expect": cal,
			"forbid": [],
		},
		{
			"id": "m3",
			"category": "recencia",
			"prompt": "¿Cuál es el código de calibración vigente del banco de pruebas? Responde sólo el código; no el anterior.",
			"kind": "code",
			"expect": cal,
			"forbid": [old],
		},
		{
			"id": "m4",
			"category": "abstencion",
			"prompt": (
				"¿Cuál es el código de calibración del horno de inducción? "
				"Si no lo sabes, responde exactamente NO_LO_SE."
			),
			"kind": "abstain",
			"expect": "NO_LO_SE",
			"forbid": [],
		},
		{
			"id": "m5",
			"category": "distractor",
			"prompt": "¿Cuál es el código de calibración del banco de pruebas (no el de inventario)? Responde sólo el código.",
			"kind": "code",
			"expect": cal,
			"forbid": [inv],
		},
		{
			"id": "m6",
			"category": "solo_fichero",
			# Este dato NO está en el Bünker: solo en .red-pill/memory/panel.md.
			# Mide la iniciativa de mirar la memoria del proyecto, igual para todos.
			"prompt": "¿En qué puerto escucha el panel de administración del banco? Responde sólo el número.",
			"kind": "number",
			"expect": "9443",
			"forbid": [],
		},
		{
			"id": "m7",
			"category": "solo_bunker",
			# Este dato SOLO está en el Bünker (no hay fichero): es la capacidad
			# que ningún brazo desnudo puede suplir con `bash`.
			"prompt": "¿Cuál es el código de la válvula de purga del banco de pruebas? Responde sólo el código.",
			"kind": "code",
			"expect": codes["valve"],
			"forbid": [],
		},
	]


def make_codes(rng: random.Random) -> dict[str, str]:
	letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"

	def code() -> str:
		return f"{rng.choice(letters)}{rng.randint(0, 9)}-{rng.randint(1000, 9999)}"

	return {
		"cal": code(),
		"old": code(),
		"inv": str(rng.randint(1000, 9999)),
		"valve": code(),
	}


# ── fixture + siembra ─────────────────────────────────────────────────────


def workspace_files(codes: dict[str, str]) -> dict[str, str]:
	"""Proyecto mínimo + banco de memoria de workspace."""
	return {
		"README.md": "# Banco de pruebas\n\nProyecto de ejemplo para medir memoria.\n",
		"src/app.py": "def main():\n\tprint('banco listo')\n\n\nif __name__ == '__main__':\n\tmain()\n",
		"data/config.json": '{\n  "workers": 3,\n  "timeout_s": 30\n}\n',
		".red-pill/memory/MEMORY.md": (
			"# MEMORY.md — índice de memoria del workspace\n\n"
			f"- @calibracion.md — código de calibración vigente: {codes['cal']}.\n"
			f"- @calibracion_anterior.md — código anterior (obsoleto): {codes['old']}.\n"
			f"- @inventario.md — código de inventario: {codes['inv']}.\n"
			"- @panel.md — puerto del panel de administración.\n"
		),
		".red-pill/memory/calibracion.md": (
			"# Calibración\n\n"
			f"El código de calibración vigente del banco de pruebas es {codes['cal']}.\n"
			f"El anterior, {codes['old']}, quedó obsoleto tras la última revisión.\n"
		),
		".red-pill/memory/calibracion_anterior.md": (
			f"# Calibración anterior\n\nCódigo obsoleto: {codes['old']}. No usar.\n"
		),
		".red-pill/memory/inventario.md": (
			f"# Inventario\n\nCódigo de inventario de los armarios: {codes['inv']}.\n"
		),
		".red-pill/memory/panel.md": (
			"# Panel de administración\n\nEl panel escucha en el puerto 9443.\n"
		),
	}


def memory_texts(codes: dict[str, str]) -> list[dict]:
	return [
		{
			"text": (
				f"El código de calibración del banco de pruebas es {codes['cal']}. "
				"Es el código vigente desde la última revisión."
			),
			"importance": 4.0,
		},
		{
			"text": (
				f"El código de calibración anterior del banco de pruebas fue {codes['old']}. "
				"Quedó obsoleto tras la revisión; el vigente es otro."
			),
			"importance": 2.0,
		},
		{
			"text": f"El código de inventario de los armarios del banco de pruebas es {codes['inv']}.",
			"importance": 1.0,
		},
		{
			# Solo Bünker: no aparece en .red-pill/memory/ (tarea m7).
			"text": (
				f"El código de la válvula de purga del banco de pruebas es {codes['valve']}. "
				"Se comprobó en la última revisión del circuito."
			),
			"importance": 3.0,
		},
	]


SEED_SCRIPT = r"""
import json, sys
from red_pill.memory import MemoryManager
from qdrant_client.http import models as qm

data = json.load(sys.stdin)
mm = MemoryManager()
mm.client.delete(
    collection_name="work_memories",
    points_selector=qm.FilterSelector(
        filter=qm.Filter(must=[qm.FieldCondition(key="source", match=qm.MatchValue(value=data["source"]))])
    ),
)
ids = []
for item in data["memories"]:
    pid = mm.add_memory(
        "work_memories",
        item["text"],
        importance=float(item.get("importance", 3.0)),
        metadata={"source": data["source"], "bench_trial": data["trial"]},
    )
    ids.append(pid)
print(json.dumps({"ids": ids}))
"""


def _exec_py(script: str, stdin: str | None = None) -> subprocess.CompletedProcess:
	cmd = [
		"podman",
		"exec",
		"-i",
		"-w",
		"/src/red-pill",
		"-e",
		"PYTHONPATH=/src/red-pill/src",
		BOX,
		"/opt/py/bin/python",
		"-c",
		script,
	]
	return subprocess.run(cmd, input=stdin or "", capture_output=True, text=True, timeout=120)


def seed_memory(trial: int, codes: dict[str, str]) -> None:
	payload = json.dumps({"source": SEED_SOURCE, "trial": trial, "memories": memory_texts(codes)})
	out = _exec_py(SEED_SCRIPT, payload)
	if out.returncode != 0:
		raise RuntimeError(f"siembra falló: {(out.stderr or out.stdout)[-400:]}")


def clean_memory() -> None:
	script = (
		"import json\n"
		"from red_pill.memory import MemoryManager\n"
		"from qdrant_client.http import models as qm\n"
		"mm = MemoryManager()\n"
		"mm.client.delete(collection_name='work_memories', points_selector=qm.FilterSelector("
		"filter=qm.Filter(must=[qm.FieldCondition(key='source', match=qm.MatchValue(value='%s'))])))\n"
		"print('cleaned')\n" % SEED_SOURCE
	)
	_exec_py(script)


def reset_workspace(codes: dict[str, str]) -> None:
	subprocess.run(["podman", "exec", BOX, "rm", "-rf", GUEST], check=False, capture_output=True)
	tmp = Path(tempfile.mkdtemp(prefix="membench-"))
	try:
		for rel, content in workspace_files(codes).items():
			path = tmp / rel
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(content, encoding="utf-8")
		subprocess.run(["podman", "cp", f"{tmp}/.", f"{BOX}:{GUEST}"], check=False, capture_output=True)
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


# ── ejecución de brazos ───────────────────────────────────────────────────


def parse_pi_json(raw: str) -> tuple[str, int, str, list[str]]:
	"""Devuelve (texto, nº de tool calls, contexto inyectado, comandos).

	El contexto inyectado separa «el RAG no trajo el dato» de «lo trajo y el
	modelo lo ignoró». Los comandos permiten auditar de dónde salió un acierto
	(p. ej. si un brazo desnudo leyó el journal del relay).
	"""
	last_text = ""
	tool_calls = 0
	injected: list[str] = []
	commands: list[str] = []
	for line in raw.splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			event = json.loads(line)
		except ValueError:
			continue
		message = event.get("message") or {}
		custom_type = message.get("customType")
		if custom_type:
			content = message.get("content")
			if isinstance(content, str):
				injected.append(content)
			continue
		if message.get("role") != "assistant":
			continue
		for block in message.get("content") or []:
			if not isinstance(block, dict):
				continue
			if block.get("type") == "toolCall":
				tool_calls += 1
				commands.append(json.dumps(block.get("arguments") or {}, ensure_ascii=False))
			elif block.get("type") == "text" and (block.get("text") or "").strip():
				last_text = block["text"]
	return last_text.strip(), tool_calls, "\n".join(injected), commands


def run_pi(arm: str, prompt: str, model: str, timeout: int) -> tuple[str, str | None, int, str, list[str]]:
	cmd = [
		"podman",
		"exec",
	]
	if arm == "dokime55":
		cmd += ["-e", "RED_PILL_SCORE_THRESHOLD=0.55"]
	cmd += [
		"-w",
		GUEST,
		BOX,
		"pi",
		"--no-session",
		"--mode",
		"json",
		"-p",
		prompt,
		"--provider",
		"local",
		"--model",
		model,
		"--tools",
		"bash",
	]
	if arm == "pi-bare":
		cmd += ["--no-extensions", "--no-mcp", "--no-skills", "--no-context-files"]
	else:
		cmd += ["--exclude-tools", "mcp__*"]
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
		answer, tool_calls, injected, commands = parse_pi_json(out.stdout or "")
		error = None
		if out.returncode != 0 and not answer:
			error = (out.stderr or "").strip()[-200:] or f"rc={out.returncode}"
		return answer, error, tool_calls, injected, commands
	except subprocess.TimeoutExpired as exc:
		raw = exc.stdout or ""
		if isinstance(raw, bytes):
			raw = raw.decode(errors="replace")
		answer, tool_calls, injected, commands = parse_pi_json(raw)
		return answer, f"timeout {timeout}s", tool_calls, injected, commands


def run_minion(prompt: str, model: str, profile: str, timeout: int) -> tuple[str, str | None, int]:
	cmd = [
		"podman",
		"exec",
		BOX,
		"/opt/py/bin/python",
		RUNNER,
		"--cwd",
		GUEST,
		"--prompt",
		prompt,
		"--model",
		profile,
		"--alias",
		model,
		"--temperature",
		"0.8",
		"--top-p",
		"0.95",
		"--max-tokens",
		"1024",
		"--seed",
		"42",
	]
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
		lines = (out.stdout or "").strip().splitlines()
		data = json.loads(lines[-1]) if lines else {}
		error = data.get("error") or ((out.stderr or "").strip()[-200:] if out.returncode != 0 else None)
		return str(data.get("answer") or ""), error, int(data.get("tool_calls") or 0)
	except subprocess.TimeoutExpired:
		return "", f"timeout {timeout}s", 0
	except (ValueError, json.JSONDecodeError) as exc:
		return (out.stdout or "").strip(), f"salida no JSON: {exc}", 0


# ── corrección ────────────────────────────────────────────────────────────


def norm(text: str) -> str:
	t = unicodedata.normalize("NFD", str(text).lower())
	t = "".join(c for c in t if unicodedata.category(c) != "Mn")
	return re.sub(r"\s+", " ", t).strip()


def has_code(text: str) -> bool:
	return bool(re.search(r"\b[A-Z]\d-\d{4}\b", text, re.I) or re.search(r"\b\d{4}\b", text))


def grade(task: dict, answer: str) -> bool:
	text = norm(answer)
	if not text:
		return False
	if task["kind"] == "abstain":
		refused = bool(re.search(r"no[ _-]?lo[ _-]?se|no tengo|desconozco|no dispongo|sin informacion|no hay (dato|informacion)", text))
		return refused and not has_code(answer)
	expect = norm(task["expect"])
	found = bool(re.search(rf"(?<![\w.]){re.escape(expect)}(?![\w])", text))
	if task["kind"] == "number":
		found = bool(re.search(rf"(?<![\d.]){re.escape(expect)}(?:[.,]0+)?(?![\d])", text))
	if not found:
		return False
	for forbidden in task.get("forbid") or []:
		if norm(forbidden) and re.search(rf"(?<![\w.]){re.escape(norm(forbidden))}(?![\w])", text):
			return False
	return True


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--trials", type=int, default=1)
	ap.add_argument("--only", default=None, help="ids de tarea separados por coma (m1..m6)")
	ap.add_argument("--arms", default="minion,pi-bare,dokime,dokime55")
	ap.add_argument("--model", default="spark")
	ap.add_argument("--profile", default="spark_x2_6_4b")
	ap.add_argument("--timeout", type=int, default=75, help="presupuesto por ejecución (s)")
	ap.add_argument("--seed", type=int, default=42)
	ap.add_argument("--keep", action="store_true", help="no borrar los puntos sembrados al terminar")
	args = ap.parse_args()

	arms = [a.strip() for a in args.arms.split(",") if a.strip()]
	OUT_DIR.mkdir(parents=True, exist_ok=True)
	stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	jsonl = OUT_DIR / f"MEMORY_{args.model}_{stamp}.jsonl"
	rows: list[dict] = []
	t0 = time.time()

	subprocess.run(
		["podman", "cp", str(Path(__file__).resolve().parent / "bench_minion_runner.py"), f"{BOX}:{RUNNER}"],
		check=False,
		capture_output=True,
	)

	rng = random.Random(args.seed)
	try:
		with jsonl.open("w", encoding="utf-8") as fh:
			for trial in range(1, args.trials + 1):
				codes = make_codes(rng)
				tasks = build_tasks(codes)
				if args.only:
					wanted = {s.strip() for s in args.only.split(",")}
					tasks = [t for t in tasks if t["id"] in wanted]
				print(f"\n=== trial {trial} códigos {codes} ===", flush=True)
				seed_memory(trial, codes)
				reset_workspace(codes)
				for task in tasks:
					order = arms[:]
					rng.shuffle(order)
					if task["id"] == "m7":
						# El turno de Dokimé queda escrito en external_turns/ y en la
						# cola (legible por bash). Si corre antes, el desnudo lee la
						# respuesta del mismo trial y m7 deja de medir el Búnker.
						order.sort(key=lambda a: a.startswith("dokime"))
					for arm in order:
						start = time.time()
						injected = ""
						commands: list[str] = []
						if arm == "minion":
							answer, error, tool_calls = run_minion(task["prompt"], args.model, args.profile, args.timeout)
						else:
							answer, error, tool_calls, injected, commands = run_pi(arm, task["prompt"], args.model, args.timeout)
						row = {
							"arm": arm,
							"task": task["id"],
							"category": task["category"],
							"trial": trial,
							"codes": codes,
							"pass": grade(task, answer),
							"expect": task["expect"],
							"forbid": task.get("forbid") or [],
							"answer": answer[-400:],
							"error": error,
							"tool_calls": tool_calls,
							"injected_hit": (
								None
								if arm == "minion" or task["kind"] == "abstain"
								else bool(task["expect"] and task["expect"] in injected)
							),
							"injected_s": len(injected),
							"commands": commands[:40],
							"elapsed_s": round(time.time() - start, 2),
							"order": order.index(arm),
						}
						rows.append(row)
						fh.write(json.dumps(row, ensure_ascii=False) + "\n")
						fh.flush()
						mark = "OK " if row["pass"] else "NO "
						print(
							f"t{trial} {task['id']:>2} {arm:9s} {mark} {row['elapsed_s']:6.1f}s "
							f"tools={tool_calls:2d} esperado={task['expect']!r} :: {row['answer'][:70]!r}"
							+ (f" ERR={error[:60]!r}" if error else ""),
							flush=True,
						)
	finally:
		if not args.keep:
			clean_memory()

	summary = summarize(rows, arms, args.trials, args.model, args.timeout)
	md = OUT_DIR / f"MEMORY_{args.model}_{stamp}_SUMMARY.md"
	md.write_text(summary, encoding="utf-8")
	print(f"\n{summary}\nResultados: {jsonl}\nResumen: {md}\nTiempo total: {time.time() - t0:.0f}s")
	return 0


def summarize(rows: list[dict], arms: list[str], trials: int, model: str, timeout: int) -> str:
	lines = [f"# Batería de memoria — {model} — {trials} trial(s) — presupuesto {timeout}s", ""]
	lines.append("## Global")
	lines.append("| brazo | pass | total | pass@1 | sin respuesta | timeouts | RAG inyectó | tools medios | tiempo medio |")
	lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
	for arm in arms:
		sub = [r for r in rows if r["arm"] == arm]
		if not sub:
			continue
		ok = sum(1 for r in sub if r["pass"])
		empty = sum(1 for r in sub if not (r["answer"] or "").strip())
		touts = sum(1 for r in sub if (r["error"] or "").startswith("timeout"))
		tools = sum(r["tool_calls"] for r in sub) / len(sub)
		mean_t = sum(r["elapsed_s"] for r in sub) / len(sub)
		scored = [r for r in sub if r.get("injected_hit") is not None]
		inj = sum(1 for r in scored if r["injected_hit"])
		inj_cell = f"{inj}/{len(scored)}" if scored else "—"
		lines.append(
			f"| {arm} | {ok} | {len(sub)} | {ok / len(sub):.1%} | {empty} | {touts} | {inj_cell} | {tools:.1f} | {mean_t:.1f}s |"
		)

	lines.append("\n## Por categoría (aciertos / runs)")
	cats = sorted({r["category"] for r in rows})
	lines.append("| categoría | " + " | ".join(arms) + " |")
	lines.append("|---|" + "---:|" * len(arms))
	for cat in cats:
		cells = []
		for arm in arms:
			sub = [r for r in rows if r["arm"] == arm and r["category"] == cat]
			ok = sum(1 for r in sub if r["pass"])
			cells.append(f"{ok}/{len(sub)}" if sub else "—")
		lines.append(f"| {cat} | " + " | ".join(cells) + " |")

	lines.append("\n## Por tarea (aciertos / runs)")
	lines.append("| tarea | " + " | ".join(arms) + " |")
	lines.append("|---|" + "---:|" * len(arms))
	for task_id in sorted({r["task"] for r in rows}):
		cells = []
		for arm in arms:
			sub = [r for r in rows if r["arm"] == arm and r["task"] == task_id]
			ok = sum(1 for r in sub if r["pass"])
			cells.append(f"{ok}/{len(sub)}" if sub else "—")
		lines.append(f"| {task_id} | " + " | ".join(cells) + " |")

	rag_rows = [r for r in rows if r.get("injected_hit") is not None]
	if rag_rows:
		lines.append("\n## Bünker: ¿inyectó? ¿acertó?")
		lines.append("| brazo | tarea | trial | inyectó el dato | acertó | tools |")
		lines.append("|---|---:|---:|---|---:|---:|")
		for r in rag_rows:
			lines.append(
				f"| {r['arm']} | {r['task']} | {r['trial']} | {'sí' if r['injected_hit'] else 'no'} | "
				f"{'sí' if r['pass'] else 'no'} | {r['tool_calls']} |"
			)

	lines.append("\n## Fallos (respuesta, error, tools)")
	lines.append("| brazo | tarea | trial | respuesta | error | tools |")
	lines.append("|---|---:|---:|---|---|---:|")
	for r in rows:
		if r["pass"]:
			continue
		answer = (r["answer"] or "").replace("|", "\\|").replace("\n", " ")[:110]
		error = (r["error"] or "").replace("|", "\\|")[:60]
		lines.append(f"| {r['arm']} | {r['task']} | {r['trial']} | {answer!r} | {error!r} | {r['tool_calls']} |")

	lines.append("\n## Lectura")
	lines.append("- `recall_literal` / `recall_parafrase`: mismo dato, distinta redacción. La diferencia mide el umbral del RAG.")
	lines.append("- `recencia` y `distractor`: el dato correcto compite con uno viejo / con otro código.")
	lines.append("- `abstencion`: no hay dato; acierta quien dice NO_LO_SE sin inventar un código.")
	lines.append("- `solo_fichero`: el dato NO está en el Búnker; mide la iniciativa de mirar `.red-pill/memory/`.")
	lines.append("- `solo_bunker`: el dato SOLO está en el Búnker; ningún brazo desnudo puede suplirlo con `bash`.")
	lines.append("- `RAG inyectó`: de las tareas con dato esperado, en cuántas el bloque inyectado contenía ese dato (no si el modelo lo usó).")
	return "\n".join(lines) + "\n"


if __name__ == "__main__":
	raise SystemExit(main())
