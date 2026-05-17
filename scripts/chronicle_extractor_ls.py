#!/usr/bin/env python3
"""
Chronicle Extractor (Phase 1)
Safely extracts conversations from the IDE LanguageServer to the unencrypted storage.
Idempotent: Only extracts if the .pb file is newer than the .json file.
"""

import json
import logging
from pathlib import Path

# Configurar logging básico (ligero para cron)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("Extractor")

try:
	from red_pill.utils.antigravity_history.api import get_all_trajectories_merged, get_trajectory_steps
	from red_pill.utils.antigravity_history.discovery import discover_language_servers, find_all_endpoints
	from red_pill.utils.antigravity_history.formatters import build_conversation_record
	from red_pill.utils.antigravity_history.parser import FieldLevel, parse_steps
except ImportError:
	logger.error("Faltan dependencias. Ejecuta este script desde el entorno virtual de red_pill.")
	exit(1)


def run_extraction():
	conv_dir = Path.home() / ".gemini/antigravity/conversations"
	out_dir = Path.home() / ".local/share/red-pill/unencrypted_conversations"
	out_dir.mkdir(parents=True, exist_ok=True)

	# 1. Comprobar Idempotencia (mtime)
	needs_export = []
	for pb_file in conv_dir.glob("*.pb"):
		json_file = out_dir / f"{pb_file.stem}.json"

		# Si el JSON no existe, o si el PB es más nuevo
		if not json_file.exists() or pb_file.stat().st_mtime > json_file.stat().st_mtime:
			needs_export.append(pb_file.stem)

	if not needs_export:
		logger.info("Estado Idempotente: Ninguna conversación modificada. Saliendo limpiamente.")
		return

	logger.info(f"Detectadas {len(needs_export)} conversaciones nuevas o modificadas.")

	# 2. Descubrir LanguageServer (IDE Abierto)
	servers = discover_language_servers()
	if not servers:
		logger.info("LanguageServer no detectado (IDE cerrado). Abortando volcado hasta la próxima ventana.")
		return

	endpoints = find_all_endpoints(servers)
	if not endpoints:
		logger.warning("Servidor de lenguaje encontrado pero puertos inaccesibles.")
		return

	ep = endpoints[0]
	p, c = ep["port"], ep["csrf"]

	# Obtener sumarios para títulos y conteo de pasos
	summaries, cascade_ep, failed_eps = get_all_trajectories_merged(endpoints)

	# 3. Extraer e Inyectar
	exported = 0
	for cid in needs_export:
		info = summaries.get(cid, {"summary": "Unknown", "stepCount": 1000})
		try:
			steps = get_trajectory_steps(p, c, cid, step_count=info.get("stepCount", 1000))
			if steps:
				messages = parse_steps(steps, FieldLevel.DEFAULT)
				record = build_conversation_record(cid, info.get("summary", ""), info, messages)

				with open(out_dir / f"{cid}.json", "w", encoding="utf-8") as f:
					json.dump(record, f, indent=2, ensure_ascii=False)
				exported += 1
				logger.info(f"  -> Volcado: {cid[:8]}... ({len(messages)} mensajes)")
		except Exception as e:
			logger.error(f"Fallo al extraer {cid}: {e}")

	logger.info(f"Fase 1 completada: {exported} conversaciones guardadas en {out_dir}")


if __name__ == "__main__":
	run_extraction()
