import logging
import os
import sys
from pathlib import Path

import platformdirs

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


def get_aleth_core_root() -> Path:
	"""
	Resuelve el directorio transversal Aleth_Core.
	Usa la variable de entorno ALETH_CORE_DIR si existe, sino asume que está al mismo nivel que el bunker_root.
	"""
	aleth_core_str = os.getenv("ALETH_CORE_DIR")
	if aleth_core_str:
		return Path(aleth_core_str)
	return get_bunker_root().parent / "Aleth_Core"


def get_data_dir() -> Path:
	"""Resuelve el directorio de datos XDG base para red-pill."""
	path = Path(platformdirs.user_data_dir("red-pill"))
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_db_dir() -> Path:
	path = get_data_dir() / "db"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_models_dir() -> Path:
	path = get_data_dir() / "models"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_queue_dir() -> Path:
	path = get_data_dir() / "queue"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_state_dir() -> Path:
	path = get_data_dir() / "state"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_keys_dir() -> Path:
	path = get_data_dir() / "keys"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_unencrypted_conversations_dir() -> Path:
	path = get_data_dir() / "unencrypted_conversations"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_backups_dir() -> Path:
	"""Resuelve el directorio de backups, configurable por el usuario."""
	env_backup = os.getenv("RED_PILL_BACKUP_DIR")
	if env_backup:
		path = Path(env_backup)
	else:
		# Por defecto: <IA_DIR>/backups/red-pill
		path = get_bunker_root().parent / "backups" / "red-pill"
	path.mkdir(parents=True, exist_ok=True)
	return path
