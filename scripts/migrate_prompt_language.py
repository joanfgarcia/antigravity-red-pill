#!/usr/bin/env python3
"""Idioma de la capa curada (MEMENTO_PROMPT_LANGUAGE) — instalación/actualización.

PROMPT-001 F3 introdujo `MEMENTO_PROMPT_LANGUAGE` (auto|es|en|ca|...). Este
script lo resuelve de forma **idempotente** durante install/upgrade:

- Si la clave YA existe en el .env → no se toca (la elección del Operador manda).
- Si no existe: `--language X` > detección del locale > default `es`.
- `--print`: solo imprime el detectado (el instalador lo usa como default de su
	pregunta), sin escribir.
- `--ask`: si hay TTY, pregunta con el detectado como default; sin TTY o en
	modo automático, solo detecta.

Solo stdlib: el instalador lo invoca antes de que el venv esté listo.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

KEY = "MEMENTO_PROMPT_LANGUAGE"
SUPPORTED = ("auto", "es", "en", "ca", "gl", "eu", "fr", "de", "pt", "it")
DEFAULT = "es"
DEFAULT_ENV_FILE = Path.home() / ".config" / "red-pill" / ".env"


def detect_language(env: dict | None = None) -> str:
	"""Detecta el idioma del locale (LC_ALL > LC_MESSAGES > LANG)."""
	env = env if env is not None else dict(os.environ)
	for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
		raw = str(env.get(var) or "").strip()
		if not raw:
			continue
		code = raw.split("_")[0].split(".")[0].split("@")[0].lower()
		if code in SUPPORTED:
			return code
	return DEFAULT


def read_env_value(path: Path) -> str | None:
	"""Valor actual de la clave en el .env (None si no está)."""
	try:
		lines = path.read_text(encoding="utf-8").splitlines()
	except OSError:
		return None
	prefix = f"{KEY}="
	for line in lines:
		stripped = line.strip()
		if stripped.startswith(prefix):
			return stripped[len(prefix) :].strip().strip('"').strip("'")
	return None


def ensure(path: Path, language: str) -> tuple[str, str]:
	"""Escribe la clave si falta. Devuelve (acción, valor final)."""
	current = read_env_value(path)
	if current:
		return "kept", current
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("a", encoding="utf-8") as fh:
		fh.write(f"{KEY}={language}\n")
	return "set", language


def _ask(detected: str) -> str:
	options = "|".join(SUPPORTED)
	try:
		answer = input(f"Idioma de los prompts de memoria ({options}) [{detected}]: ").strip()
	except EOFError:
		return detected
	if not answer:
		return detected
	return answer if answer in SUPPORTED else detected


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help=f"Ruta del .env (default: {DEFAULT_ENV_FILE})")
	parser.add_argument("--language", default=None, help="Valor explícito (auto|es|en|ca|gl|eu|fr|de|pt|it)")
	parser.add_argument("--print", dest="print_only", action="store_true", help="Solo imprime el idioma detectado (sin escribir)")
	parser.add_argument("--ask", action="store_true", help="Preguntar en TTY (default: detectar en silencio)")
	args = parser.parse_args()

	detected = detect_language()
	if args.print_only:
		print(detected)
		return 0

	if args.language:
		value = args.language.strip().lower()
		if value not in SUPPORTED:
			print(f"[prompt-language] Valor no soportado '{args.language}'; usando {detected}.", file=sys.stderr)
			value = detected
	elif args.ask and sys.stdin.isatty():
		value = _ask(detected)
	else:
		value = detected

	action, final = ensure(args.env_file, value)
	if action == "kept":
		print(f"[prompt-language] {KEY}={final} (existente, preservado)")
	else:
		print(f"[prompt-language] {KEY}={final} (detectado del locale; editable en {args.env_file})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
