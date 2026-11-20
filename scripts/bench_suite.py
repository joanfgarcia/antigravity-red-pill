#!/usr/bin/env python3
"""bench_suite.py — 15 tareas verificables a través del arnés real (pi).

Cada tarea tiene una respuesta esperada que se deriva del propio fixture (no se escribe a
mano), así que el grader no puede "tener razón" por accidente. Se ejecuta una sesión nueva
por tarea para no arrastrar contexto.

Uso:  python scripts/bench_suite.py [--model spark] [--only 1,2,3]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path

HOST_FIXTURE = Path("/tmp/opencode/benchfix")
GUEST_FIXTURE = "/srv/dokime/bench"
MODEL = "spark"


def build_fixture() -> dict[str, str]:
	files = {
		"src/alpha.py": """import os


def load(path):
    return open(path).read()


async def fetch(url):
    return url


def save(path, data):
    return len(data)


async def flush_buffers():
    return None
""",
		"src/beta.js": """// utilidades
function add(a, b) { return a + b }
function sub(a, b) { return a - b }
const mul = (a, b) => a * b
export { add, sub, mul }
""",
		"src/gamma.py": """def parse(text):
    return text.split()


def parse(text, sep):
    return text.split(sep)


def render(items):
    return ",".join(items)
""",
		"src/delta.py": """import json
import os
import re


def dump(obj):
    return json.dumps(obj)


def scan(root):
    return [os.path.join(root, f) for f in os.listdir(root)]


def clean(text):
    return re.sub(r"\\s+", " ", text).strip()
""",
		"config/app.yaml": """name: bench
retries: 4
timeout_s: 30
verbose: false
region: eu-west
""",
		"config/limits.json": """{"max_items": 25, "batch": 5, "workers": 3}""",
		"data/scores.csv": """name,score
ana,10
luis,7
marta,13
""",
		"logs/app.log": """INFO start
WARN slow
ERROR disk full
INFO retry
ERROR timeout
INFO done
""",
		"docs/README.md": """# bench

- El banco mide identidad y memoria.
- Toda tarea deja evidencia verificable.
- No se inventan resultados nunca.
""",
		"schema.sql": """CREATE TABLE users (id INTEGER, name TEXT, email TEXT);
CREATE TABLE events (id INTEGER, kind TEXT);
CREATE TABLE notes (id INTEGER, body TEXT, author TEXT, created_at TEXT);
""",
		"src/legacy.py": """# TODO: quitar el parche
def old():
    return 1


# TODO: documentar
def older():
    return 2
""",
		"pyproject.toml": """[project]
name = "bench-fixture"
version = "2.4.1"
""",
	}
	root = HOST_FIXTURE
	if root.exists():
		subprocess.run(["rm", "-rf", str(root)], check=False)
	for path, content in files.items():
		dest = root / path
		dest.parent.mkdir(parents=True, exist_ok=True)
		dest.write_text(content, encoding="utf-8")
	return files


def derive(files: dict[str, str]) -> list[dict[str, str]]:
	alpha = files["src/alpha.py"]
	beta = files["src/beta.js"]
	delta = files["src/delta.py"]
	yaml_cfg = files["config/app.yaml"]
	csv = files["data/scores.csv"]
	log = files["logs/app.log"]
	sql = files["schema.sql"]
	readme = files["docs/README.md"]
	legacy = files["src/legacy.py"]
	pyproject = files["pyproject.toml"]

	async_alpha = len(re.findall(r"^async def ", alpha, re.M))
	funcs_alpha = len(re.findall(r"^(?:async )?def ", alpha, re.M))
	js_functions = len(re.findall(r"function\s+\w+|=>", beta))
	yaml_keys = len([ln for ln in yaml_cfg.splitlines() if re.match(r"^\w+:", ln)])
	total_score = sum(int(ln.split(",")[1]) for ln in csv.splitlines()[1:] if ln.strip())
	errors = len(re.findall(r"^ERROR ", log, re.M))
	todos = len(re.findall(r"TODO:", legacy))
	version = re.search(r'version = "([^"]+)"', pyproject).group(1)
	notes_cols = len(re.search(r"CREATE TABLE notes \(([^)]+)\)", sql).group(1).split(","))
	bullets = len(re.findall(r"^- ", readme, re.M))
	imports_delta = len([ln for ln in delta.splitlines() if ln.startswith("import ")])
	longest = max(re.findall(r"^(?:async )?def (\w+)", alpha, re.M), key=len)
	workers = json.loads(files["config/limits.json"])["workers"]

	return [
		{"id": "1", "prompt": "¿Cuántas funciones async hay en src/alpha.py? Responde sólo con el número.", "expect": str(async_alpha)},
		{"id": "2", "prompt": "¿Cuántas funciones (def, incluidas async) hay en src/alpha.py? Sólo el número.", "expect": str(funcs_alpha)},
		{"id": "3", "prompt": "¿Qué fichero declara dos veces la misma función? Responde con su ruta.", "expect": "gamma.py"},
		{"id": "4", "prompt": "¿Cuántas claves de primer nivel tiene config/app.yaml? Sólo el número.", "expect": str(yaml_keys)},
		{"id": "5", "prompt": "Suma la columna score de data/scores.csv. Sólo el número.", "expect": str(total_score)},
		{"id": "6", "prompt": "¿Cuántas líneas ERROR hay en logs/app.log? Sólo el número.", "expect": str(errors)},
		{"id": "7", "prompt": "¿Cuántos comentarios TODO hay en src/legacy.py? Sólo el número.", "expect": str(todos)},
		{"id": "8", "prompt": "¿Qué versión declara pyproject.toml? Sólo la versión.", "expect": version},
		{"id": "9", "prompt": "¿Cuántas columnas tiene la tabla notes en schema.sql? Sólo el número.", "expect": str(notes_cols)},
		{"id": "10", "prompt": "¿Cuántos puntos (líneas que empiezan por guion) tiene docs/README.md? Sólo el número.", "expect": str(bullets)},
		{"id": "11", "prompt": "En src/delta.py, ¿cuántas líneas 'import ...' hay? Sólo el número.", "expect": str(imports_delta)},
		{"id": "12", "prompt": "¿Cuál es el nombre de la función MÁS LARGA (en caracteres) de src/alpha.py? Sólo el nombre.", "expect": longest},
		{"id": "13", "prompt": "¿Cuántas funciones declara src/beta.js (function y arrow)? Sólo el número.", "expect": str(js_functions)},
		{"id": "14", "prompt": "¿Cuántos workers declara config/limits.json? Sólo el número.", "expect": str(workers)},
		{
			"id": "15",
			"prompt": "¿Cuántos ficheros .py hay bajo src/? Sólo el número.",
			"expect": str(len([p for p in files if p.startswith("src/") and p.endswith(".py")])),
		},
	]


def norm(text: str) -> str:
	t = unicodedata.normalize("NFD", text.lower())
	t = "".join(c for c in t if unicodedata.category(c) != "Mn")
	return re.sub(r"\s+", " ", t).strip()


def run_task(task: dict[str, str], model: str) -> tuple[bool, str]:
	prompt = task["prompt"].replace('"', '\\"')
	cmd = [
		"podman",
		"exec",
		"-w",
		GUEST_FIXTURE,
		"dokime",
		"sh",
		"-lc",
		f'timeout 420 pi --session-id bench-t{task["id"]} -p "{prompt}" --provider local --model {model} --mode text',
	]
	out = subprocess.run(cmd, capture_output=True, text=True, timeout=460)
	text = (out.stdout or "").strip()
	return norm(task["expect"]) in norm(text), text[-400:]


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--model", default=MODEL)
	ap.add_argument("--only", default=None, help="ids separados por coma")
	args = ap.parse_args()

	files = build_fixture()
	tasks = derive(files)
	if args.only:
		wanted = {s.strip() for s in args.only.split(",")}
		tasks = [t for t in tasks if t["id"] in wanted]

	subprocess.run(["podman", "exec", "dokime", "sh", "-lc", f"rm -rf {GUEST_FIXTURE} && mkdir -p {GUEST_FIXTURE}"], check=False)
	subprocess.run(["podman", "cp", f"{HOST_FIXTURE}/.", f"dokime:{GUEST_FIXTURE}"], check=False)
	# Sesiones limpias: sin esto la segunda corrida arrastra el historial de la primera.
	subprocess.run(
		["podman", "exec", "dokime", "sh", "-lc", "rm -f /srv/dokime/home/.pi/agent/sessions/--srv-dokime-bench--/*bench-t*.jsonl"], check=False
	)

	ok = 0
	rows = []
	for task in tasks:
		passed, text = run_task(task, args.model)
		ok += 1 if passed else 0
		rows.append((task["id"], passed, task["expect"], text[:110].replace("\n", " ")))
		print(f"{task['id']:>2} {'OK ' if passed else 'NO '} esperado={task['expect']!r} :: {text[:110]!r}", flush=True)

	print(f"\nRESULTADO {ok}/{len(tasks)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
