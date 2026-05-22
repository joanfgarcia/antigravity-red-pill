#!/usr/bin/env python3
"""
Chronicle Extractor (Phase 1) - AES Decryption Mode
Safely extracts conversations by directly decrypting the Protobuf files using ANTIGRAVITY_KEY.
Idempotent: Only extracts if the .pb file is newer than the .json file.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Configurar logging básico
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ExtractorAES")


def run_extraction():
	key = os.environ.get("ANTIGRAVITY_KEY")
	if not key:
		logger.error("ANTIGRAVITY_KEY no encontrada en el entorno.")
		return

	conv_dir = Path.home() / ".gemini/antigravity/conversations"
	out_dir = Path.home() / ".local/share/red-pill/unencrypted_conversations"
	out_dir.mkdir(parents=True, exist_ok=True)

	# 1. Comprobar Idempotencia (mtime)
	needs_export = []
	for pb_file in conv_dir.glob("*.pb"):
		json_file = out_dir / f"{pb_file.stem}.json"

		# Si el JSON no existe, o si el PB es más nuevo
		if not json_file.exists() or pb_file.stat().st_mtime > json_file.stat().st_mtime:
			needs_export.append(pb_file)

	if not needs_export:
		logger.info("Estado Idempotente: Ninguna conversación modificada. Saliendo limpiamente.")
		return

	logger.info(f"Detectadas {len(needs_export)} conversaciones pendientes de descifrado AES.")

	# 2. Descifrar vía AES
	tmp_dir = Path("/tmp/ag_aes_extract")
	if tmp_dir.exists():
		shutil.rmtree(tmp_dir)
	tmp_dir.mkdir(parents=True)

	scripts_dir = Path(__file__).parent
	decrypt_script = scripts_dir / "antigravity_decrypt.py"

	exported = 0
	for pb_file in needs_export:
		cid = pb_file.stem
		try:
			tmp_output_file = tmp_dir / f"{cid}_decrypted.json"
			cmd = [sys.executable, str(decrypt_script), str(pb_file), "--output", str(tmp_output_file), "--key", key, "--format", "json"]
			result = subprocess.run(cmd, capture_output=True, text=True)

			if result.returncode == 0:
				# El script de AES genera <cid>_decrypted.json
				decrypted_file = tmp_dir / f"{cid}_decrypted.json"
				if decrypted_file.exists():
					shutil.copy2(decrypted_file, out_dir / f"{cid}.json")
					exported += 1
					logger.info(f"  -> Volcado (AES): {cid[:8]}...")
				else:
					logger.error(f"Fallo al encontrar salida AES para {cid}")
			else:
				logger.error(f"Fallo al descifrar {cid}: {result.stderr}")

		except Exception as e:
			logger.error(f"Fallo inesperado al descifrar {cid}: {e}")

	logger.info(f"Fase 1 (AES) completada: {exported} conversaciones guardadas en {out_dir}")


if __name__ == "__main__":
	run_extraction()
