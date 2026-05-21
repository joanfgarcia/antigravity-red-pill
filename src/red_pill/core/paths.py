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


def migrate_legacy_xdg_config() -> None:
	"""
	Autonomously bridges the migration from legacy underscored ~/.config/red_pill
	to the XDG-standard hyphenated ~/.config/red-pill directory.
	"""
	import logging
	import shutil
	from pathlib import Path

	import platformdirs

	logger = logging.getLogger(__name__)

	legacy_dir = Path.home() / ".config" / "red_pill"
	target_dir = Path(platformdirs.user_config_dir("red-pill"))

	if legacy_dir.exists() and legacy_dir.is_dir():
		logger.info(f"[XDG-MIGRATION] Legacy directory found at {legacy_dir}. Initiating bridge...")
		target_dir.mkdir(parents=True, exist_ok=True)

		assets = ["vault.seed", "vault_group.state", "vault_identity.state", "recovery.key", "swarm_groups"]
		migrated_any = False

		for asset in assets:
			source_path = legacy_dir / asset
			target_path = target_dir / asset

			if source_path.exists() and not target_path.exists():
				logger.info(f"[XDG-MIGRATION] Migrating {asset} -> {target_path}")
				try:
					if source_path.is_dir():
						shutil.copytree(source_path, target_path, dirs_exist_ok=True)
					else:
						shutil.copy2(source_path, target_path)
					migrated_any = True
				except Exception as e:
					logger.error(f"[XDG-MIGRATION] Failed to migrate {asset}: {e}")

		if migrated_any:
			logger.info("[XDG-MIGRATION] Migration complete. Retaining legacy directory as backup.")


def resolve_model_path(model_filename: str) -> Path:
	"""Resuelve la ruta absoluta de un archivo de modelo dentro del directorio de modelos."""
	return get_models_dir() / model_filename


def get_daemon_dir() -> Path:
	"""Resuelve el directorio de ejecución del daemon del modelo (~/.agent/model-daemon)."""
	return Path.home() / ".agent" / "model-daemon"


def get_model_profiles_path() -> Path:
	"""Resuelve la ruta del archivo de configuración de perfiles de modelos (~/.agent/model_profiles.yaml)."""
	return Path.home() / ".agent" / "model_profiles.yaml"

