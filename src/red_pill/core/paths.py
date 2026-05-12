import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def get_bunker_root() -> Path:
	"""
	Resuelve el directorio maestro del Bünker Soberano.
	Valida la existencia y permisos de escritura (vital en entornos inmutables/Flatpak).
	"""
	bunker_path_str = os.getenv("IA_DIR")
	if bunker_path_str:
		path = Path(bunker_path_str)
	else:
		path = Path.home() / "Documents" / "IA" / "sharing"

	# Si no existe, intentar crearlo
	if not path.exists():
		try:
			path.mkdir(parents=True, exist_ok=True)
			logger.info(f"[PATHS] Created bunker root: {path}")
		except Exception as e:
			logger.error(f"[PATHS] FATAL: Cannot create bunker root at {path}: {e}")
			sys.exit(1)

	# Validar permisos R/W (crítico en Docker/Podman/Silverblue)
	if not os.access(path, os.R_OK | os.W_OK):
		logger.error(f"[PATHS] FATAL: Bunker root '{path}' is not read/write accessible. Check container volumes or permissions.")
		sys.exit(1)

	return path


def get_bunker_root_str() -> str:
	"""Convenience method para APIs antiguas que requieren strings."""
	return str(get_bunker_root())
