#!/usr/bin/env python3
"""Sandbox E2E del scribe dual de opencode (v1 + v2) — P0.5 (plan OpenCode V2).

Monta un HOME/XDG aislado, crea una bunker_queue.db de prueba con el esquema
completo de memory_queue, despliega el plugin del seed (con ${QUEUE_DB}
sustituido) y lanza un turno real contra el binario elegido. Verifica que la
captura aterriza en la cola. No toca el sistema vivo: todo vive bajo --workdir.

Uso:
	python3 scripts/opencode_v2_sandbox.py --binary ~/.opencode/bin/opencode
	python3 scripts/opencode_v2_sandbox.py --download-v2 2.0.16
	python3 scripts/opencode_v2_sandbox.py --binary /tmp/opencode/v2bin/opencode --keep
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_PLUGIN = os.path.join(REPO_ROOT, "seeds", "opencode", "plugins", "redpill-scribe.js")
PROMPT = "Responde SOLO con la palabra: sandbox"

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_queue (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	prompt TEXT NOT NULL,
	response TEXT NOT NULL,
	role TEXT NOT NULL,
	status TEXT DEFAULT 'pending',
	created_at REAL,
	category TEXT DEFAULT 'mixed',
	originator TEXT,
	model TEXT,
	content_hash TEXT,
	session_id TEXT,
	affinity TEXT
)
"""


def log(msg: str) -> None:
	print(f"  {msg}")


def download_v2(version: str, workdir: str) -> str:
	system = platform.system().lower()
	machine = platform.machine().lower()
	if system != "linux" or machine not in ("x86_64", "amd64"):
		raise SystemExit(f"descarga automática no soportada en {system}/{machine}; pasa --binary")
	url = f"https://opencode.ai/files/bin/{version}/opencode-linux-x64.tar.gz"
	dest = os.path.join(workdir, "bin")
	os.makedirs(dest, exist_ok=True)
	tar_path = os.path.join(dest, "opencode.tar.gz")
	log(f"descargando {url}")
	urllib.request.urlretrieve(url, tar_path)
	with tarfile.open(tar_path) as tf:
		tf.extractall(dest)
	binary = os.path.join(dest, "opencode")
	os.chmod(binary, 0o755)
	return binary


def build_sandbox(workdir: str, plugin_src: str) -> tuple[str, str, str]:
	home = os.path.join(workdir, "home")
	config = os.path.join(home, ".config", "opencode")
	plugins = os.path.join(config, "plugins")
	project = os.path.join(workdir, "project")
	for d in (plugins, project):
		os.makedirs(d, exist_ok=True)
	queue_db = os.path.join(workdir, "bunker_queue.db")
	con = sqlite3.connect(queue_db)
	con.executescript(SCHEMA)
	con.commit()
	con.close()
	with open(plugin_src, encoding="utf-8") as f:
		code = f.read()
	code = code.replace("${QUEUE_DB}", queue_db)
	code = code.replace("${STATE_DIR}", os.path.join(workdir, "state"))
	with open(os.path.join(plugins, "redpill-scribe.js"), "w", encoding="utf-8") as f:
		f.write(code)
	return home, project, queue_db


def detect_major(binary: str) -> int:
	try:
		out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout
	except Exception:
		return 1
	match = re.search(r"(\d+)\.\d+", out or "")
	return int(match.group(1)) if match else 1


def run_turn(binary: str, home: str, project: str, timeout: int) -> subprocess.CompletedProcess:
	env = dict(os.environ)
	env.update(
		{
			"HOME": home,
			"XDG_CONFIG_HOME": os.path.join(home, ".config"),
			"XDG_DATA_HOME": os.path.join(home, ".local", "share"),
			"XDG_CACHE_HOME": os.path.join(home, ".cache"),
			"REDPILL_SCRIBE_DISABLE": "0",
		}
	)
	args = [binary, "run"]
	if detect_major(binary) >= 2:
		# v2 comparte un servicio de fondo por usuario; --standalone fuerza un
		# servidor privado para que cargue el config/plugin del sandbox.
		args.append("--standalone")
	args += ["--format", "json", PROMPT]
	return subprocess.run(
		args,
		cwd=project,
		env=env,
		capture_output=True,
		text=True,
		timeout=timeout,
	)


def verify_capture(queue_db: str) -> tuple[bool, str]:
	con = sqlite3.connect(queue_db)
	row = con.execute("SELECT prompt, response, originator, session_id FROM memory_queue ORDER BY id DESC LIMIT 1").fetchone()
	con.close()
	if not row:
		return False, "sin filas en memory_queue"
	prompt, response, originator, session_id = row
	if not prompt or not response:
		return False, f"fila incompleta: prompt={prompt!r} response={response!r}"
	return True, f"originator={originator} session_id={session_id} prompt={prompt[:40]!r} response={response[:40]!r}"


def main() -> int:
	parser = argparse.ArgumentParser(description="Sandbox E2E del scribe dual de opencode (v1 + v2).")
	parser.add_argument("--binary", help="binario de opencode a probar (v1 o v2)")
	parser.add_argument("--download-v2", metavar="VERSION", help="descarga el binario v2 indicado (p. ej. 2.0.16)")
	parser.add_argument("--plugin", default=DEFAULT_PLUGIN, help="plugin a desplegar (default: seed del repo)")
	parser.add_argument("--workdir", help="directorio de trabajo aislado (default: mktemp)")
	parser.add_argument("--keep", action="store_true", help="no borrar el workdir al terminar")
	parser.add_argument("--timeout", type=int, default=180)
	args = parser.parse_args()

	if not args.binary and not args.download_v2:
		parser.error("pasa --binary o --download-v2")

	workdir = args.workdir or tempfile.mkdtemp(prefix="opencode-sandbox-")
	os.makedirs(workdir, exist_ok=True)
	log(f"workdir: {workdir}")

	try:
		binary = args.binary
		if args.download_v2:
			binary = download_v2(args.download_v2, workdir)
		if not binary or not os.path.exists(binary):
			print(f"FAIL: binario no encontrado: {binary}")
			return 1

		home, project, queue_db = build_sandbox(workdir, args.plugin)
		try:
			result = run_turn(binary, home, project, args.timeout)
		except subprocess.TimeoutExpired:
			print(f"FAIL: timeout de {args.timeout}s en el turno")
			return 1
		if result.returncode != 0:
			print("FAIL: el turno terminó con código", result.returncode)
			print((result.stderr or result.stdout)[-800:])
			return 1

		ok, detail = verify_capture(queue_db)
		print(("PASS: " if ok else "FAIL: ") + detail)
		return 0 if ok else 1
	finally:
		if not args.keep and not args.workdir:
			shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
	sys.exit(main())
