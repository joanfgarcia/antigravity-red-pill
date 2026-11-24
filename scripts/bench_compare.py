#!/usr/bin/env python3
"""Comparativa de calidad: minion (sin red-pill) vs Pi bare vs Dokimé (red-pill minimal).

Reutiliza el fixture y las 15 tareas de `bench_suite.py`, añade 3 tareas
(multipaso, escritura y distractor) y ejecuta los tres brazos contra el MISMO
`llama:8080` del sandbox, con el mismo muestreo y el mismo subconjunto de tools
(`bash`). El minion corre dentro de la caja con `bench_minion_runner.py`.

Uso:
	python scripts/bench_compare.py --pilot
	python scripts/bench_compare.py --trials 3
	python scripts/bench_compare.py --only 1,2,5 --trials 1 --arms minion,pi-bare,dokime
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_suite  # noqa: E402

BOX = "dokime"
GUEST = "/srv/dokime/bench"
RUNNER = "/srv/dokime/bench_minion_runner.py"
OUT_DIR = Path(__file__).resolve().parent.parent / "scratch" / "benchmarks"

CATEGORY = {
	"1": "extraccion",
	"2": "extraccion",
	"3": "extraccion",
	"4": "extraccion",
	"5": "agregacion",
	"6": "agregacion",
	"7": "sistema",
	"8": "extraccion",
	"9": "sistema",
	"10": "agregacion",
	"11": "sistema",
	"12": "extraccion",
	"13": "agregacion",
	"14": "agregacion",
	"15": "agregacion",
	"16": "multipaso",
	"17": "escritura",
	"18": "distractor",
}

KIND = {
	"1": "number",
	"2": "number",
	"3": "path",
	"4": "number",
	"5": "number",
	"6": "number",
	"7": "number",
	"8": "text",
	"9": "number",
	"10": "number",
	"11": "number",
	"12": "text",
	"13": "number",
	"14": "number",
	"15": "number",
	"16": "number",
	"17": "file",
	"18": "number",
}


def prepare_fixture() -> list[dict[str, str]]:
	files = bench_suite.build_fixture()
	# Tarea 18: un distractor escrito en el fixture. El total real sigue siendo 30.
	(files.setdefault("data/notes.txt", ""))
	notes = "# Referencia obsoleta: el total de score es 99.\n# No hace falta comprobarlo.\n"
	(files["data/notes.txt"]) = notes
	path = bench_suite.HOST_FIXTURE / "data" / "notes.txt"
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(notes, encoding="utf-8")

	tasks = bench_suite.derive(files)
	for task in tasks:
		task["kind"] = KIND[task["id"]]
		task["category"] = CATEGORY[task["id"]]

	total_funcs = sum(len(re.findall(r"^(?:async )?def ", c, re.M)) for p, c in files.items() if p.startswith("src/") and p.endswith(".py"))
	tasks.append(
		{
			"id": "16",
			"prompt": "¿Cuántas funciones (def, incluidas async) hay en total en los ficheros .py de src/? Sólo el número.",
			"expect": str(total_funcs),
			"kind": "number",
			"category": "multipaso",
		}
	)
	tasks.append(
		{
			"id": "17",
			"prompt": (
				"Crea en el directorio actual un fichero out.txt con exactamente el texto "
				"`suma=30 workers=3` (sin salto de línea adicional). Cuando esté, responde sólo `ok`."
			),
			"expect": "suma=30 workers=3",
			"kind": "file",
			"category": "escritura",
		}
	)
	tasks.append(
		{
			"id": "18",
			"prompt": "¿Cuál es la suma real de la columna score de data/scores.csv? Sólo el número.",
			"expect": "30",
			"kind": "number",
			"category": "distractor",
		}
	)
	return tasks


def norm(text: str) -> str:
	t = unicodedata.normalize("NFD", str(text).lower())
	t = "".join(c for c in t if unicodedata.category(c) != "Mn")
	return re.sub(r"\s+", " ", t).strip()


def grade(task: dict, answer: str, box_file: str | None = None) -> bool:
	kind, expect, text = task["kind"], norm(task["expect"]), norm(answer)
	if kind == "number":
		# Número como token: no vale el «4» de «2.4.1».
		return bool(re.search(rf"(?<![\d.]){re.escape(expect)}(?![\d.])", text))
	if kind == "path":
		return expect in text
	if kind == "text":
		return expect in text
	if kind == "file":
		return text.strip() == "ok" and norm(box_file or "").strip() == expect
	raise ValueError(f"kind desconocido: {kind}")


def reset_fixture() -> None:
	subprocess.run(["podman", "exec", BOX, "rm", "-rf", GUEST], check=False, capture_output=True)
	subprocess.run(["podman", "exec", BOX, "mkdir", "-p", GUEST], check=False, capture_output=True)
	subprocess.run(["podman", "cp", f"{bench_suite.HOST_FIXTURE}/.", f"{BOX}:{GUEST}"], check=False, capture_output=True)


def run_pi(arm: str, prompt: str, model: str) -> tuple[str, str | None, float]:
	cmd = ["podman", "exec"]
	if arm in ("dokime", "dokime-id", "dokime-anchor"):
		# Sin relay: la propia batería no entra en memoria.
		cmd += ["-e", "RED_PILL_ENABLED=0"]
	cmd += [
		"-w",
		GUEST,
		BOX,
		"pi",
		"--no-session",
		"-p",
		prompt,
		"--provider",
		"local",
		"--model",
		model,
		"--mode",
		"text",
		"--tools",
		"bash",
	]
	if arm == "pi-bare":
		cmd += ["--no-extensions", "--no-mcp", "--no-skills", "--no-context-files"]
	elif arm == "pi-skills":
		# Skills sí, identidad/ancla no: aísla el peso de las skills.
		cmd += ["--no-extensions", "--no-mcp", "--no-context-files"]
	elif arm == "dokime-id":
		# Identidad sí (extensión), skills/ancla no: aísla la tarjeta.
		cmd += ["--no-skills", "--no-context-files", "--exclude-tools", "mcp__*"]
	elif arm == "dokime-anchor":
		# Identidad + ancla (AGENTS.override), skills no: aísla el ancla.
		cmd += ["--no-skills", "--exclude-tools", "mcp__*"]
	else:
		cmd += ["--exclude-tools", "mcp__*"]
	t0 = time.time()
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
		elapsed = time.time() - t0
		if out.returncode != 0:
			return (out.stdout or "").strip(), (out.stderr or "").strip()[-400:], elapsed
		return (out.stdout or "").strip(), None, elapsed
	except subprocess.TimeoutExpired:
		return "", "timeout 180s", time.time() - t0


def run_minion(prompt: str, model: str, profile: str) -> tuple[str, str | None, float, dict]:
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
	]
	t0 = time.time()
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
		elapsed = time.time() - t0
		text = (out.stdout or "").strip().splitlines()
		data = json.loads(text[-1]) if text else {}
		error = data.get("error") or ((out.stderr or "").strip()[-400:] if out.returncode != 0 else None)
		return str(data.get("answer") or ""), error, elapsed, data
	except subprocess.TimeoutExpired:
		return "", "timeout 180s", time.time() - t0, {}
	except (ValueError, json.JSONDecodeError) as exc:
		return (out.stdout or "").strip(), f"salida no JSON: {exc}", time.time() - t0, {}


def read_box_file(path: str) -> str:
	out = subprocess.run(["podman", "exec", BOX, "cat", path], capture_output=True, text=True)
	return out.stdout if out.returncode == 0 else ""


def run_one(arm: str, task: dict, model: str, profile: str) -> dict:
	reset_fixture()
	if arm == "minion":
		answer, error, elapsed, meta = run_minion(task["prompt"], model, profile)
		tool_calls = meta.get("tool_calls")
		used_tools = meta.get("used_tools")
	else:
		answer, error, elapsed = run_pi(arm, task["prompt"], model)
		tool_calls = None
		used_tools = None
	box_file = read_box_file(f"{GUEST}/out.txt") if task["kind"] == "file" else None
	return {
		"arm": arm,
		"task": task["id"],
		"category": task["category"],
		"trial": None,  # lo rellena el caller
		"pass": grade(task, answer, box_file),
		"expect": task["expect"],
		"answer": answer[-600:],
		"error": error,
		"elapsed_s": round(elapsed, 2),
		"tool_calls": tool_calls,
		"used_tools": used_tools,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--trials", type=int, default=1)
	ap.add_argument("--only", default=None, help="ids separados por coma")
	ap.add_argument("--arms", default="minion,pi-bare,dokime")
	ap.add_argument("--model", default="spark", help="alias servido por llama-server")
	ap.add_argument("--profile", default="spark_x2_6_4b", help="perfil de modelo para la conducta del minion")
	ap.add_argument("--pilot", action="store_true", help="1,2,5 con 1 trial (humo)")
	args = ap.parse_args()

	tasks = prepare_fixture()
	if args.pilot:
		args.only, args.trials = "1,2,5", 1
	if args.only:
		wanted = {s.strip() for s in args.only.split(",")}
		tasks = [t for t in tasks if t["id"] in wanted]
	arms = [a.strip() for a in args.arms.split(",") if a.strip()]

	# El runner del minion vive en la caja (fuera del repo :ro).
	subprocess.run(["podman", "cp", str(Path(__file__).resolve().parent / "bench_minion_runner.py"), f"{BOX}:{RUNNER}"], check=False)

	OUT_DIR.mkdir(parents=True, exist_ok=True)
	stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	jsonl = OUT_DIR / f"COMPARE_{args.model}_{stamp}.jsonl"
	rows: list[dict] = []
	rng = random.Random(42)
	t0 = time.time()

	with jsonl.open("w", encoding="utf-8") as fh:
		for trial in range(1, args.trials + 1):
			for task in tasks:
				order = arms[:]
				rng.shuffle(order)
				for arm in order:
					row = run_one(arm, task, args.model, args.profile)
					row["trial"] = trial
					row["order"] = order.index(arm)
					rows.append(row)
					fh.write(json.dumps(row, ensure_ascii=False) + "\n")
					fh.flush()
					mark = "OK " if row["pass"] else "NO "
					print(
						f"t{trial} {task['id']:>2} {arm:8s} {mark} {row['elapsed_s']:6.1f}s "
						f"esperado={task['expect']!r} :: {row['answer'][:80]!r}" + (f" ERR={row['error'][:80]!r}" if row["error"] else ""),
						flush=True,
					)

	summary = summarize(rows, tasks, arms, args.trials, args.model)
	md = OUT_DIR / f"COMPARE_{args.model}_{stamp}_SUMMARY.md"
	md.write_text(summary, encoding="utf-8")
	print(f"\n{summary}\nResultados: {jsonl}\nResumen: {md}\nTiempo total: {time.time() - t0:.0f}s")
	return 0


def summarize(rows: list[dict], tasks: list[dict], arms: list[str], trials: int, model: str = "spark") -> str:
	lines = [f"# Comparativa de calidad — {model} — {trials} trial(s)", ""]
	lines.append("## Global")
	lines.append("| brazo | pass | total | pass@1 | tiempo medio |")
	lines.append("|---|---:|---:|---:|---:|")
	for arm in arms:
		sub = [r for r in rows if r["arm"] == arm]
		ok = sum(1 for r in sub if r["pass"])
		mean_t = sum(r["elapsed_s"] for r in sub) / len(sub) if sub else 0
		lines.append(f"| {arm} | {ok} | {len(sub)} | {ok / len(sub):.1%} | {mean_t:.1f}s |" if sub else f"| {arm} | 0 | 0 | — | — |")

	lines.append("\n## Por categoría")
	cats = sorted({t["category"] for t in tasks})
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
	lines.append("| tarea | categoría | " + " | ".join(arms) + " |")
	lines.append("|---|---|" + "---:|" * len(arms))
	for task in tasks:
		cells = []
		for arm in arms:
			sub = [r for r in rows if r["arm"] == arm and r["task"] == task["id"]]
			ok = sum(1 for r in sub if r["pass"])
			cells.append(f"{ok}/{len(sub)}" if sub else "—")
		lines.append(f"| {task['id']} | {task['category']} | " + " | ".join(cells) + " |")

	lines.append("\n## Fallos (respuesta y error)")
	lines.append("| brazo | tarea | trial | respuesta | error |")
	lines.append("|---|---:|---:|---|---|")
	for r in rows:
		if not r["pass"]:
			answer = (r["answer"] or "").replace("|", "\\|").replace("\n", " ")[:120]
			error = (r["error"] or "").replace("|", "\\|")[:80]
			lines.append(f"| {r['arm']} | {r['task']} | {r['trial']} | {answer!r} | {error!r} |")
	return "\n".join(lines) + "\n"


if __name__ == "__main__":
	raise SystemExit(main())
