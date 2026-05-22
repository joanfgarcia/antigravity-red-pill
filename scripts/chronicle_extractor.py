#!/usr/bin/env python3
"""
Chronicle Extractor (Orchestrator)
Decide if we should use AES decryption (if ANTIGRAVITY_KEY exists)
or fallback to Language Server extraction.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import platformdirs
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ExtractorOrchestrator")


def load_env():
	"""Load Red-Pill environment variables."""
	env_path = Path(platformdirs.user_config_dir("red-pill")) / ".env"
	if env_path.exists():
		load_dotenv(env_path)
	else:
		load_dotenv()


def main():
	load_env()
	key = os.environ.get("ANTIGRAVITY_KEY")
	scripts_dir = Path(__file__).parent

	python_exe = sys.executable

	if key:
		logger.info("ANTIGRAVITY_KEY encontrada. Usando pipeline de descifrado AES...")
		script = scripts_dir / "chronicle_extractor_aes.py"
	else:
		logger.info("ANTIGRAVITY_KEY ausente. Usando pipeline de Extracción por Language Server...")
		script = scripts_dir / "chronicle_extractor_ls.py"

	cmd = [python_exe, str(script)]
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError as e:
		logger.error(f"El extractor falló con el código de salida {e.returncode}")


if __name__ == "__main__":
	main()
