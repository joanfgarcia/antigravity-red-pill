#!/usr/bin/env python3
"""memento_validate.py — validación de contenido (MEM-006): notas rechazadas por el filtro de ruido.

QUÉ ES / PARA QUÉ
	Revisa con el LLM local las notas que el filtro de ruido (`is_garbage`) rechazó
	al ascender: decide si son memoria legítima (approve) o ruido real (reject) y
	**sella el veredicto** en el frontmatter (self-documented):
	`validator_approved`, `validator` (engine), `validator_prompt_version`,
	`validator_reason`, `validated_at`. Aprobada → el ascenso la sube con
	`content_verified=True` (exención quirúrgica, nunca `immune`).

HISTORIA
	Nació del incidente de las 13 notas (2026-09-23): el gate de curaduría decía
	"vale" y el filtro de contenido decía "parece CI" — dos puertas ortogonales.
	En vez de bajar el filtro, se añade esta revisión: excepción auditada.

USO (piloto / bulk)
	uv run python scripts/memento_validate.py --list          # pendientes (JSON; element_job)
	uv run python scripts/memento_validate.py                 # procesa RP_ELEMENT (una nota)
	Job: configs/jobs/memento_validate.yaml (element_job → checkpoint POR NOTA,
	pausable/reanudable). En el sueño irá como fase antes de la ascensión (tras el piloto).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from red_pill.memento import get_memento_root
from red_pill.memento.agentic import http_transport, pending_validations, validate_note


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--list", action="store_true", help="Imprime las notas pendientes (JSON).")
	parser.add_argument("--root", type=Path, default=None, help="Raíz Memento (default: la configurada).")
	args = parser.parse_args()
	root = args.root or get_memento_root()

	if args.list:
		print(json.dumps([{"path": str(p)} for p in pending_validations(root)], ensure_ascii=False))
		return
	raw = os.environ.get("RP_ELEMENT")
	if not raw:
		print("RP_ELEMENT no definido (usa el job element_job) o pasa --list")
		sys.exit(2)
	el = json.loads(raw)
	try:
		stats = validate_note(http_transport, Path(str(el["path"])))
	except Exception as e:
		from red_pill.memento.agentic.runner import _is_llm_connection_error

		if _is_llm_connection_error(e):
			print(f"[DEFER] LLM no disponible: {e}")
			sys.exit(int(os.environ.get("RP_DEFER_EXIT_CODE", 77)))
		raise
	print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
	main()
