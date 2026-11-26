#!/usr/bin/env python3
"""Batería de techo para Dokimé: lo que un 27B debería hacer y un 9B no.

`bench_compare.py` (18 tareas de un salto) está saturado: un 4B saca 18/18.
Esto mide el techo, no el suelo. El diseño no copia ningún benchmark; toma
prestadas sus **decisiones de medición**:

- **BFCL v3** → se gradúa el *estado final* del fixture, no la prosa; los pasos
  de más no fallan (se miden como coste); perturbaciones `miss_func`/`miss_param`.
- **τ-bench** → `pass^k` (los k intentos pasan) y un **brazo nulo** que no hace
  nada: si puntúa, la tarea está mal diseñada.
- **IFEval / M-IFEval** → nivel prompt vs nivel instrucción, y estricto vs laxo
  (sin vallas de markdown, sin primera/última línea).
- **RULER** → longitud útil con seguimiento de variables y agregación, no needle.
- **LongMemEval** → taxonomía de memoria: multi-sesión, actualización, abstención.

Cinco familias, 12 tareas, todo verificable por código:

    cadena         a1 base · a2 miss_func · a3 miss_param
    restricciones  b1 prosa acotada · b2 JSON estricto · b3 negación
    memoria        c1 multi-sesión · c2 actualización · c3 abstención
    ventana        d1 seguimiento de variables · d2 agregación
    recuperacion   e1 comando que falla: diagnosticar y reparar

Regla del brazo nulo: una respuesta vacía y un estado intacto tienen que sacar
**0** en nivel prompt. Si no, la tarea se marca inválida.

Uso:
    python scripts/bench_hard.py --list
    python scripts/bench_hard.py --dry-run                # valida tareas y nulo, sin caja
    python scripts/bench_hard.py --model bonsai25 --arms dokime,null --trials 1
    python scripts/bench_hard.py --merge f1.jsonl,f2.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import statistics
import subprocess
import time
import unicodedata
from datetime import datetime
from pathlib import Path

BOX = "dokime"
GUEST = "/srv/dokime/bench_hard"
RUNNER = "/srv/dokime/bench_minion_runner.py"
OUT_DIR = Path(__file__).resolve().parent.parent / "scratch" / "benchmarks"
HOST_ROOT = Path("/tmp/opencode/benchhard")


# ── utilidades de texto ───────────────────────────────────────────────────


def norm(text: str) -> str:
	t = unicodedata.normalize("NFD", str(text).lower())
	t = "".join(c for c in t if unicodedata.category(c) != "Mn")
	return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
	return [w for w in re.split(r"\s+", text.strip()) if w]


def sentences(text: str) -> list[str]:
	return [s for s in re.split(r"[.!?]+(?:\s|$)", text.strip()) if s.strip()]


def _json_obj(text: str, loose: bool) -> dict:
	t = text.strip()
	if loose:
		t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.M).strip()
		i, j = t.find("{"), t.rfind("}")
		if i >= 0 and j > i:
			t = t[i : j + 1]
	obj = json.loads(t)
	if not isinstance(obj, dict):
		raise ValueError("no es un objeto JSON")
	return obj


# ── comprobaciones ────────────────────────────────────────────────────────
#
# Cada comprobación devuelve (ok, detalle). `guard=True` significa: tiene que
# cumplirse para aprobar la tarea, pero no cuenta como instrucción (si no, el
# brazo nulo aprobaría «no mencionar 99» sin haber escrito nada).


def check_one(chk: dict, answer: str, state: dict[str, str], task: dict) -> tuple[bool, str]:
	kind = chk["kind"]
	ans = answer or ""

	if kind == "ans_has":
		ok = bool(ans.strip()) and norm(chk["text"]) in norm(ans)
		return ok, f"contiene {chk['text']!r}"

	if kind == "ans_absent":
		ok = bool(ans.strip()) and norm(chk["text"]) not in norm(ans)
		return ok, f"no menciona {chk['text']!r}"

	if kind == "ans_regex":
		hit = bool(re.search(chk["pattern"], ans))
		ok = bool(ans.strip()) and (not hit if chk.get("absent") else hit)
		return ok, f"{'no casa' if chk.get('absent') else 'casa'} {chk['pattern']}"

	if kind == "ans_endswith":
		ok = bool(ans.strip()) and norm(ans).rstrip(" .,;:!?").endswith(norm(chk["text"]))
		return ok, f"termina en {chk['text']!r}"

	if kind == "ans_startswith":
		ok = bool(ans.strip()) and norm(ans).lstrip().startswith(norm(chk["text"]))
		return ok, f"empieza por {chk['text']!r}"

	if kind == "ans_words":
		n = len(words(ans))
		ok = bool(ans.strip()) and chk["min"] <= n <= chk["max"]
		return ok, f"{n} palabras (rango {chk['min']}–{chk['max']})"

	if kind == "ans_sentences":
		n = len(sentences(ans))
		ok = bool(ans.strip()) and n == chk["count"]
		return ok, f"{n} frases (esperadas {chk['count']})"

	if kind == "ans_no_digits":
		ok = bool(ans.strip()) and not re.search(r"\d", ans)
		return ok, "sin dígitos"

	if kind == "ans_accents":
		n = len(re.findall(r"[áéíóúüÁÉÍÓÚÜñÑ]", ans))
		ok = bool(ans.strip()) and n >= chk["min"]
		return ok, f"{n} caracteres acentuados (mínimo {chk['min']})"

	if kind == "ans_json":
		strict_ok = True
		try:
			obj = _json_obj(ans, loose=False)
			strict_ok = True
		except Exception:
			strict_ok = False
			try:
				obj = _json_obj(ans, loose=True)
			except Exception as exc:
				return False, f"JSON inválido: {exc}"
		for key, expected in (chk.get("equals") or {}).items():
			if str(obj.get(key)) != str(expected):
				return False, f"{key}={obj.get(key)!r} (esperado {expected!r})"
		for key in chk.get("keys") or []:
			if key not in obj:
				return False, f"falta la clave {key!r}"
		if chk.get("strict") and not strict_ok:
			return False, "JSON válido pero envuelto en texto o vallas"
		return True, "JSON correcto" + ("" if strict_ok else " (laxo)")

	if kind == "file_exact":
		got = state.get(chk["path"])
		ok = got is not None and got.strip() == chk["text"].strip()
		return ok, f"{chk['path']} == {chk['text']!r} (hay {got!r:.60})"

	if kind == "file_has":
		got = state.get(chk["path"]) or ""
		ok = norm(chk["text"]) in norm(got)
		return ok, f"{chk['path']} contiene {chk['text']!r}"

	if kind == "file_lines":
		got = (state.get(chk["path"]) or "").replace("\r\n", "\n").strip().split("\n")
		got = [ln.strip() for ln in got if ln.strip() != ""]
		ok = got == list(chk["lines"])
		return ok, f"{chk['path']} líneas {got[:4]}"

	if kind == "file_no_digits":
		got = state.get(chk["path"]) or ""
		ok = bool(got.strip()) and not re.search(r"\d", got)
		return ok, f"{chk['path']} sin dígitos"

	if kind == "file_absent":
		ok = not (state.get(chk["path"]) or "").strip()
		return ok, f"{chk['path']} no debe existir o estar vacío"

	if kind == "unchanged":
		expected = task["fixture"].get(chk["path"], "")
		ok = state.get(chk["path"]) == expected
		return ok, f"{chk['path']} intacto"

	raise ValueError(f"comprobación desconocida: {kind}")


def grade(task: dict, answer: str, state: dict[str, str], overrides: dict[str, bool] | None = None) -> dict:
	overrides = overrides or {}
	results = []
	for chk in task["checks"]:
		if chk["id"] in overrides:
			ok, detail = overrides[chk["id"]], "reejecutado en la caja"
		elif chk["kind"] == "rerun":
			ok, detail = False, "no ejecutado"
		else:
			ok, detail = check_one(chk, answer, state, task)
		results.append(
			{
				"id": chk.get("id") or chk["kind"],
				"ok": ok,
				"guard": bool(chk.get("guard")),
				"detail": detail,
			}
		)
	instr = [r for r in results if not r["guard"]]
	return {
		"pass": all(r["ok"] for r in results),
		"instruction_ok": sum(1 for r in instr if r["ok"]),
		"instruction_total": len(instr),
		"checks": results,
	}


# ── fixtures ──────────────────────────────────────────────────────────────
#
# Todo se deriva del fixture generado: el grader no puede «acertar por
# accidente» con una constante escrita a mano.


def _module(n_funcs: int, n_async: int) -> str:
	lines = ["import json", "", ""]
	for i in range(n_funcs):
		if i < n_async:
			lines += [f"async def tarea_{i}(datos):", f"    return datos[{i}]", ""]
		else:
			lines += [f"def tarea_{i}(datos):", f"    return list(datos)[{i}]", ""]
	return "\n".join(lines)


def task_a1() -> dict:
	funcs, workers = 7, 3
	riesgo = "alto" if funcs > workers * 2 else "bajo"
	files = {
		"src/core.py": _module(funcs, 2),
		"data/config.json": json.dumps({"workers": workers, "timeout_s": 30}, indent=2) + "\n",
		"docs/README.md": "# Planta\n\nLos módulos viven en src/ y la configuración en data/.\n",
	}
	return {
		"id": "a1",
		"family": "cadena",
		"prompt": (
			"Lee src/core.py y data/config.json. Crea el fichero `out/report.md` con "
			"exactamente estas tres líneas, en este orden y sin nada más:\n"
			"funcs=<n>\nworkers=<n>\nriesgo=<alto|bajo>\n"
			"Donde `riesgo` es `alto` si funcs > workers*2. No inventes cifras."
		),
		"fixture": files,
		"checks": [
			{
				"id": "funcs",
				"kind": "file_lines",
				"path": "out/report.md",
				"lines": [f"funcs={funcs}", f"workers={workers}", f"riesgo={riesgo}"],
			},
		],
	}


def task_a2() -> dict:
	files = {
		"README.md": "# Validación\n\nPara validar: `tools/validate.sh data/input.json`.\n",
		"tools/.keep": "",
		"data/input.json": '{"n": 5}\n',
	}
	return {
		"id": "a2",
		"family": "cadena",
		"prompt": (
			"Ejecuta `tools/validate.sh data/input.json` y escribe su salida en "
			"`out/result.txt`. Si la herramienta no existe, escribe exactamente "
			"`NO_EXISTE: tools/validate.sh` en ese fichero y no inventes un resultado."
		),
		"fixture": files,
		"checks": [
			{
				"id": "abstiene",
				"kind": "file_exact",
				"path": "out/result.txt",
				"text": "NO_EXISTE: tools/validate.sh",
			},
			{"id": "sin_inventar", "kind": "file_no_digits", "path": "out/result.txt"},
		],
	}


def task_a3() -> dict:
	files = {
		"data/config.json": json.dumps({"workers": 3, "timeout_s": 30}, indent=2) + "\n",
		"data/scores.csv": "id,score\n1,12\n2,88\n3,55\n4,91\n5,7\n6,64\n",
		"scripts/clasifica.py": (
			"import csv, json\n\n"
			"cfg = json.load(open('data/config.json'))\n"
			"umbral = cfg['threshold']\n"
			"filas = list(csv.DictReader(open('data/scores.csv')))\n"
			"print(sum(1 for f in filas if int(f['score']) > umbral))\n"
		),
	}
	return {
		"id": "a3",
		"family": "cadena",
		"prompt": (
			"Clasifica data/scores.csv con el umbral de data/config.json y escribe en "
			"`out/alta.txt` cuántas filas superan el umbral. Si falta el umbral en la "
			"configuración, escribe exactamente `FALTA: threshold` y no supongas un valor."
		),
		"fixture": files,
		"checks": [
			{"id": "abstiene", "kind": "file_exact", "path": "out/alta.txt", "text": "FALTA: threshold"},
			{"id": "sin_suposicion", "kind": "file_no_digits", "path": "out/alta.txt"},
		],
	}


def task_b1() -> dict:
	files = {
		"data/config.json": json.dumps({"workers": 3, "timeout_s": 30}, indent=2) + "\n",
	}
	return {
		"id": "b1",
		"family": "restricciones",
		"prompt": (
			"Explica en primera persona, en un solo párrafo de entre 60 y 80 palabras, "
			"qué guarda data/config.json. Reglas: no escribas ningún dígito; usa al "
			"menos dos caracteres acentuados (tildes o eñes); termina exactamente con "
			"la frase `y nada más` (sin punto final)."
		),
		"fixture": files,
		"checks": [
			{"id": "longitud", "kind": "ans_words", "min": 60, "max": 80},
			{"id": "sin_digitos", "kind": "ans_no_digits"},
			{"id": "acentos", "kind": "ans_accents", "min": 2},
			{"id": "cierre", "kind": "ans_endswith", "text": "y nada más"},
		],
	}


def task_b2() -> dict:
	files = {"data/config.json": json.dumps({"workers": 3, "timeout_s": 30}, indent=2) + "\n"}
	return {
		"id": "b2",
		"family": "restricciones",
		"prompt": (
			"Devuelve SOLO un objeto JSON válido, sin texto alrededor y sin vallas de "
			"código, con las claves `servicio`, `workers` y `riesgo`. Responde directamente, "
			"sin usar herramientas. `workers` debe ser el número real de data/config.json, "
			'como número (no como cadena). `riesgo` es "alto" si workers > 2. `servicio` en '
			"minúsculas y sin espacios. Puedes leer data/config.json con bash si lo necesitas."
		),
		"fixture": files,
		"timeout": 240,
		"checks": [
			{
				"id": "json",
				"kind": "ans_json",
				"strict": True,
				"keys": ["servicio", "workers", "riesgo"],
				"equals": {"workers": 3, "riesgo": "alto"},
			},
			{"id": "sin_vallas", "kind": "ans_absent", "text": "```"},
		],
	}


def task_b3() -> dict:
	files = {
		"data/notes.md": (
			"# Notas de cierre\n\n"
			"El total de score es 30 y cuadra con el recuento del fixture.\n"
			"Una nota antigua decía 99; era obsoleta y no debe usarse.\n"
		)
	}
	return {
		"id": "b3",
		"family": "restricciones",
		"prompt": (
			"Resume data/notes.md en exactamente dos frases. No menciones la cifra 99 "
			"ni la palabra «obsoleta». La cifra correcta debe aparecer."
		),
		"fixture": files,
		"checks": [
			{"id": "dos_frases", "kind": "ans_sentences", "count": 2},
			{"id": "sin_vieja", "kind": "ans_absent", "text": "99"},
			{"id": "sin_obsoleta", "kind": "ans_absent", "text": "obsoleta"},
			{"id": "con_30", "kind": "ans_has", "text": "30"},
		],
	}


def task_c1() -> dict:
	base, doble = 4096, 8192
	files = {
		".red-pill/memory/MEMORY.md": (
			"# MEMORY.md\n\n- @sesion_2026-11-01.md — despliegue de ingesta.\n"
			"- @sesion_2026-11-10.md — panel de administración.\n"
		),
		".red-pill/memory/sesion_2026-11-01.md": (
			f"# 2026-11-01\n\nLevantamos el servicio de ingesta en el puerto {base}.\n"
		),
		".red-pill/memory/sesion_2026-11-10.md": (
			"# 2026-11-10\n\nEl panel escucha en el doble del puerto de ingesta.\n"
		),
	}
	return {
		"id": "c1",
		"family": "memoria",
		"prompt": (
			"Según la memoria del proyecto, ¿en qué puerto escucha el panel de "
			"administración? Responde sólo el número."
		),
		"fixture": files,
		"checks": [{"id": "puerto", "kind": "ans_has", "text": str(doble)}],
	}


def task_c2() -> dict:
	viejo, nuevo = "K7-1990", "Z4-2026"
	files = {
		".red-pill/memory/MEMORY.md": (
			"# MEMORY.md\n\n- @calibracion.md — código de calibración.\n"
			"- @calibracion_2026-11-20.md — revisión de noviembre.\n"
		),
		".red-pill/memory/calibracion.md": (
			f"# Calibración\n\nEl código de calibración era {viejo}.\n"
		),
		".red-pill/memory/calibracion_2026-11-20.md": (
			f"# 2026-11-20\n\nNuevo código de calibración vigente: {nuevo}.\n"
		),
	}
	return {
		"id": "c2",
		"family": "memoria",
		"prompt": (
			"¿Cuál es el código de calibración vigente? Responde sólo el código; "
			"no el anterior."
		),
		"fixture": files,
		"checks": [
			{"id": "vigente", "kind": "ans_has", "text": nuevo},
			{"id": "no_viejo", "kind": "ans_absent", "text": viejo},
		],
	}


def task_c3() -> dict:
	files = {
		".red-pill/memory/MEMORY.md": (
			"# MEMORY.md\n\n- @calibracion.md — código de calibración.\n"
		),
		".red-pill/memory/calibracion.md": "# Calibración\n\nCódigo vigente: Z4-2026.\n",
	}
	return {
		"id": "c3",
		"family": "memoria",
		"prompt": (
			"¿Cuál es el código de la válvula de purga? Si no está en la memoria, "
			"responde exactamente NO_LO_SE."
		),
		"fixture": files,
		"checks": [
			{"id": "abstiene", "kind": "ans_has", "text": "NO_LO_SE"},
			{"id": "no_inventa", "kind": "ans_regex", "pattern": r"\b[A-Z]\d-\d{4}\b", "absent": True},
		],
	}


def _haystack(target_tokens: int, seed: int) -> list[str]:
	"""Relleno reproducible, ~4 caracteres por token."""
	rng = random.Random(seed)
	frases = [
		"En la reunión se revisaron los sistemas habituales y se acordó continuar con el plan previsto sin cambios.",
		"El equipo anotó las incidencias menores y las dejó para la revisión semanal.",
		"Los turnos quedaron cubiertos y no hubo necesidad de escalar ninguna decisión.",
	]
	n = max(24, (target_tokens * 4) // 110)
	return [rng.choice(frases) for _ in range(n)]


def task_d1() -> dict:
	seed = 20261125
	rng = random.Random(seed)
	valor = f"{rng.choice('WXYZ')}{rng.choice('LMNP')}-{rng.randint(1000, 9999)}"
	links = 12
	lines = _haystack(26000, seed)
	# config_0 ← config_1 ← … ← config_12 ← valor. Se siembra al final: hay que
	# recorrer la cadena hacia atrás, no basta con encontrar una línea suelta.
	ins = [f"config_{i} toma el valor de config_{i + 1}." for i in range(links)]
	ins.append(f"config_{links} toma el valor {valor}.")
	pos = max(1, (len(lines) - len(ins) * 2) // (len(ins) + 1))
	for i, extra in enumerate(ins):
		lines.insert(min(len(lines), pos * (i + 1) + i), extra)
	prompt = (
		f"En el texto hay una cadena de asignaciones entre config_0 y config_{links}. "
		"¿Qué valor acaba teniendo config_0? Responde sólo el valor."
	)
	return {
		"id": "d1",
		"family": "ventana",
		"prompt": "\n".join(lines) + "\n\n" + prompt,
		"fixture": {},
		"checks": [{"id": "cadena", "kind": "ans_has", "text": valor}],
		"timeout": 900,
	}


def task_d2() -> dict:
	seed = 771
	rng = random.Random(seed)
	frecuente, raro = "TAG-A1", "TAG-B2"
	lines = _haystack(24000, seed)
	for _ in range(9):
		lines.insert(rng.randrange(len(lines)), f"Etiqueta observada: {frecuente}.")
	for _ in range(4):
		lines.insert(rng.randrange(len(lines)), f"Etiqueta observada: {raro}.")
	prompt = (
		"¿Cuál de los códigos que empiezan por TAG- aparece más veces en el texto? "
		"Responde sólo el código."
	)
	return {
		"id": "d2",
		"family": "ventana",
		"prompt": "\n".join(lines) + "\n\n" + prompt,
		"fixture": {},
		"checks": [
			{"id": "mas_frecuente", "kind": "ans_has", "text": frecuente},
			{"id": "no_el_raro", "kind": "ans_absent", "text": raro},
		],
		"timeout": 900,
	}


def task_e1() -> dict:
	config = json.dumps({"workers": 3, "timeout_s": 30}, indent=2) + "\n"
	files = {
		"data/config.yaml": config,
		"scripts/despliega.sh": (
			"#!/bin/sh\n"
			"set -eu\n"
			"mkdir -p build\n"
			"cp data/conf.yaml build/conf.yaml\n"
			"echo listo\n"
		),
	}
	return {
		"id": "e1",
		"family": "recuperacion",
		"prompt": (
			"scripts/despliega.sh falla. Diagnostica por qué, arréglalo sin tocar nada "
			"bajo data/, y deja en `out/status.txt` exactamente `ok`. El script debe "
			"terminar con código 0."
		),
		"fixture": files,
		"checks": [
			{"id": "estado", "kind": "file_exact", "path": "out/status.txt", "text": "ok"},
			{"id": "datos_intactos", "kind": "unchanged", "path": "data/config.yaml", "guard": True},
			{"id": "script_ok", "kind": "rerun", "cmd": ["sh", "scripts/despliega.sh"], "exit": 0, "guard": True},
		],
	}


BUILDERS = [task_a1, task_a2, task_a3, task_b1, task_b2, task_b3, task_c1, task_c2, task_c3, task_d1, task_d2, task_e1]


def build_tasks() -> list[dict]:
	return [b() for b in BUILDERS]


# ── fixture en disco y en la caja ─────────────────────────────────────────


def write_fixture(task: dict) -> Path:
	root = HOST_ROOT / task["id"]
	if root.exists():
		shutil.rmtree(root)
	root.mkdir(parents=True)
	for rel, content in task["fixture"].items():
		path = root / rel
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content, encoding="utf-8")
	return root


def _podman(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
	return subprocess.run(["podman", *args], capture_output=True, text=True, timeout=timeout)


def reset_box_fixture(task: dict) -> None:
	root = write_fixture(task)
	_podman("exec", BOX, "rm", "-rf", GUEST)
	_podman("exec", BOX, "mkdir", "-p", f"{GUEST}/out")
	_podman("cp", f"{root}/.", f"{BOX}:{GUEST}")


def collect_state(task: dict) -> dict[str, str]:
	state: dict[str, str] = {}
	paths = {c["path"] for c in task["checks"] if "path" in c}
	for rel in paths:
		out = _podman("exec", BOX, "cat", f"{GUEST}/{rel}")
		state[rel] = out.stdout if out.returncode == 0 else ""
	return state


# ── ejecución ─────────────────────────────────────────────────────────────


def run_pi(prompt: str, model: str, timeout: int) -> tuple[str, str | None, float]:
	cmd = [
		"podman", "exec", "-e", "RED_PILL_ENABLED=0", "-w", GUEST, BOX,
		"pi", "--no-session", "-p", prompt, "--provider", "local", "--model", model,
		"--mode", "text", "--tools", "bash", "--exclude-tools", "mcp__*",
	]
	t0 = time.time()
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
		elapsed = time.time() - t0
		if out.returncode != 0:
			return (out.stdout or "").strip(), (out.stderr or "").strip()[-400:], elapsed
		return (out.stdout or "").strip(), None, elapsed
	except subprocess.TimeoutExpired:
		return "", f"timeout {timeout}s", time.time() - t0


def run_minion(
	prompt: str, model: str, profile: str, timeout: int, max_tokens: int = 2048
) -> tuple[str, str | None, float, dict]:
	cmd = [
		"podman", "exec", BOX, "/opt/py/bin/python", RUNNER,
		"--cwd", GUEST, "--prompt", prompt, "--model", profile, "--alias", model,
		"--temperature", "0.7", "--top-p", "0.9", "--max-tokens", str(max_tokens), "--seed", "42",
	]
	t0 = time.time()
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
		elapsed = time.time() - t0
		lines = (out.stdout or "").strip().splitlines()
		data = json.loads(lines[-1]) if lines else {}
		err = data.get("error") or ((out.stderr or "").strip()[-400:] if out.returncode != 0 else None)
		return str(data.get("answer") or ""), err, elapsed, data
	except subprocess.TimeoutExpired:
		return "", f"timeout {timeout}s", time.time() - t0, {}


def post_checks(task: dict) -> dict[str, bool]:
	"""Comprobaciones que exigen volver a ejecutar algo en la caja."""
	results = {}
	for chk in task["checks"]:
		if chk["kind"] != "rerun":
			continue
		out = _podman("exec", "-w", GUEST, BOX, *chk["cmd"], timeout=120)
		results[chk["id"]] = out.returncode == chk.get("exit", 0)
	return results


def run_one(
	arm: str, task: dict, model: str, profile: str, default_timeout: int = 420, max_tokens: int = 2048
) -> dict:
	reset_box_fixture(task)
	timeout = task.get("timeout", default_timeout)
	if arm == "null":
		answer, error, elapsed, meta = "", None, 0.0, {}
	elif arm == "minion":
		answer, error, elapsed, meta = run_minion(task["prompt"], model, profile, timeout, max_tokens)
	else:
		answer, error, elapsed = run_pi(task["prompt"], model, timeout)
		meta = {}
	state = collect_state(task)
	g = grade(task, answer, state, overrides=post_checks(task))
	return {
		"model": model,
		"arm": arm,
		"task": task["id"],
		"family": task["family"],
		"trial": None,
		"pass": g["pass"],
		"instruction_ok": g["instruction_ok"],
		"instruction_total": g["instruction_total"],
		"checks": g["checks"],
		"answer": answer[-800:],
		"error": error,
		"elapsed_s": round(elapsed, 2),
		"tool_calls": meta.get("tool_calls"),
	}


# ── resumen ───────────────────────────────────────────────────────────────


def _pass_k(rows: list[dict], arm: str, task_id: str, k: int) -> float:
	sub = [r for r in rows if r["arm"] == arm and r["task"] == task_id]
	if len(sub) < k:
		return 0.0
	c = sum(1 for r in sub if r["pass"])
	return 1.0 if c >= k else 0.0


def summarize(rows: list[dict], tasks: list[dict], trials: int, config: dict | None = None) -> str:
	models = sorted({r["model"] for r in rows}) or ["—"]
	arms = sorted({r["arm"] for r in rows})
	lines = [f"# Batería de techo — {', '.join(models)} — {trials} trial(s)", ""]
	if config:
		lines += ["Config: " + " · ".join(f"`{k}={v}`" for k, v in config.items()), ""]

	lines += ["## Global", "| modelo | brazo | tareas | pass^1 | pass^k | instrucción | p50 | p95 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
	for model in models:
		for arm in arms:
			sub = [r for r in rows if r["model"] == model and r["arm"] == arm]
			if not sub:
				continue
			ids = sorted({r["task"] for r in sub})
			p1 = sum(1 for r in sub if r["pass"]) / len(sub)
			pk = sum(_pass_k(sub, arm, tid, trials) for tid in ids) / len(ids)
			io = sum(r["instruction_ok"] for r in sub)
			it = sum(r["instruction_total"] for r in sub)
			instr = f"{io}/{it} ({io / it:.0%})" if it else "—"
			lat = [r["elapsed_s"] for r in sub if r["elapsed_s"]]
			p50 = statistics.median(lat) if lat else 0
			p95 = statistics.quantiles(lat, n=20)[-1] if len(lat) >= 2 else p50
			lines.append(f"| {model} | {arm} | {len(ids)} | {p1:.1%} | {pk:.1%} | {instr} | {p50:.1f}s | {p95:.1f}s |")
	lines.append("")
	lines += _null_verdict(rows)
	lines += ["## Por familia", "| familia | " + " | ".join(f"{m}/{a}" for m in models for a in arms) + " |"]
	lines.append("|---|" + "---:|" * (len(models) * len(arms)))
	for fam in sorted({t["family"] for t in tasks}):
		cells = []
		for model in models:
			for arm in arms:
				sub = [r for r in rows if r["model"] == model and r["arm"] == arm and r["family"] == fam]
				cells.append(f"{sum(1 for r in sub if r['pass'])}/{len(sub)}" if sub else "—")
		lines.append(f"| {fam} | " + " | ".join(cells) + " |")

	lines += ["", "## Fallos", "| modelo | brazo | tarea | comprobación | respuesta |", "|---|---|---|---|---|"]
	for r in rows:
		if r["pass"]:
			continue
		failed = [c["id"] for c in r["checks"] if not c["ok"]]
		answer = (r["answer"] or "").replace("|", "\\|").replace("\n", " ")[:110]
		lines.append(f"| {r['model']} | {r['arm']} | {r['task']} | {', '.join(failed)[:40]} | {answer!r} |")
	return "\n".join(lines) + "\n"


def _null_verdict(rows: list[dict]) -> list[str]:
	null = [r for r in rows if r["arm"] == "null"]
	if not null:
		return ["## Brazo nulo", "No ejecutado: la validación de la batería queda pendiente.", ""]
	ok = sum(1 for r in null if r["pass"])
	io = sum(r["instruction_ok"] for r in null)
	it = sum(r["instruction_total"] for r in null)
	verdict = "VÁLIDA" if ok == 0 and it and io / it < 0.10 else "INVÁLIDA"
	return [
		"## Brazo nulo",
		f"pass^1 = {ok}/{len(null)} · instrucción = {io}/{it} → batería **{verdict}**.",
		"(Una tarea que aprueba sin hacer nada mide otra cosa.)" if verdict == "INVÁLIDA" else "",
		"",
	]


# ── CLI ───────────────────────────────────────────────────────────────────


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--model", default="spark")
	ap.add_argument("--profile", default="spark_x2_6_4b")
	ap.add_argument("--arms", default="dokime,null")
	ap.add_argument("--trials", type=int, default=1)
	ap.add_argument("--timeout", type=int, default=420, help="segundos por tarea (d1/d2 ya piden 900)")
	ap.add_argument(
		"--max-tokens", type=int, default=2048,
		help="tope de generación por completion. Con modelos que piensan DEBE superar el "
		"presupuesto de razonamiento del servidor: si son iguales, no queda margen para "
		"la respuesta y la tarea parece colgada (AD-139)",
	)
	ap.add_argument("--only", default=None, help="ids separados por coma")
	ap.add_argument("--list", action="store_true")
	ap.add_argument("--dry-run", action="store_true", help="valida tareas y brazo nulo sin caja")
	ap.add_argument("--merge", default=None, help="jsonl separados por coma")
	args = ap.parse_args()

	if args.merge:
		rows = [json.loads(line) for p in args.merge.split(",") for line in Path(p).read_text().splitlines() if line.strip()]
		tasks = build_tasks()
		print(summarize(rows, tasks, max(r["trial"] or 1 for r in rows)))
		return 0

	tasks = build_tasks()
	if args.only:
		wanted = {s.strip() for s in args.only.split(",")}
		tasks = [t for t in tasks if t["id"] in wanted]
	if args.list:
		for t in tasks:
			print(f"{t['id']:>2} {t['family']:<14} {len(t['checks'])} comprobaciones · timeout {t.get('timeout', args.timeout)}s")
		return 0

	if args.dry_run:
		bad = 0
		for t in tasks:
			write_fixture(t)
			g = grade(t, "", {})
			if g["pass"] or g["instruction_ok"]:
				bad += 1
				print(f"  INVÁLIDA {t['id']}: el brazo nulo puntúa ({g['instruction_ok']}/{g['instruction_total']})")
			else:
				print(f"  ok {t['id']:<3} {t['family']:<14} nulo 0/{g['instruction_total']}")
		print(f"\n{'Batería válida' if bad == 0 else f'{bad} tarea(s) inválida(s)'}: {len(tasks)} tareas, fixtures en {HOST_ROOT}")
		return 0 if bad == 0 else 1

	arms = [a.strip() for a in args.arms.split(",") if a.strip()]
	_podman("cp", str(Path(__file__).resolve().parent / "bench_minion_runner.py"), f"{BOX}:{RUNNER}")
	OUT_DIR.mkdir(parents=True, exist_ok=True)
	stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	jsonl = OUT_DIR / f"BENCHHARD_{args.model}_{stamp}.jsonl"
	rows: list[dict] = []
	rng = random.Random(42)
	t0 = time.time()

	with jsonl.open("w", encoding="utf-8") as fh:
		for trial in range(1, args.trials + 1):
			for task in tasks:
				for arm in arms:
					row = run_one(arm, task, args.model, args.profile, args.timeout, args.max_tokens)
					row["trial"] = trial
					rows.append(row)
					fh.write(json.dumps(row, ensure_ascii=False) + "\n")
					fh.flush()
					print(
						f"t{trial} {task['id']:>2} {arm:<7} {'OK ' if row['pass'] else 'NO '} "
						f"{row['elapsed_s']:6.1f}s {row['instruction_ok']}/{row['instruction_total']} :: {row['answer'][:70]!r}",
						flush=True,
					)

	summary = summarize(
		rows, tasks, args.trials,
		config={"max_tokens": args.max_tokens, "timeout_s": args.timeout, "arms": args.arms},
	)
	md = OUT_DIR / f"BENCHHARD_{args.model}_{stamp}_SUMMARY.md"
	md.write_text(summary, encoding="utf-8")
	print(f"\n{summary}\nResultados: {jsonl}\nResumen: {md}\nTiempo total: {time.time() - t0:.0f}s")
	_ = rng  # reservado para barajar el orden de brazos si hiciera falta
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
