import logging
import os
import sys
from pathlib import Path

import platformdirs

logger = logging.getLogger(__name__)


def _is_test_context() -> bool:
	"""True if we are running under a test harness (pytest, or the explicit
	REDPILL_TESTING flag). Used to enforce write isolation: a test must NEVER
	touch the operator's production data dir."""
	if os.environ.get("REDPILL_TESTING") == "1":
		return True
	return "pytest" in sys.modules


def _production_dirs() -> list[Path]:
	"""The operator's REAL red-pill/neon-link locations (default XDG layout under
	the home dir, bypassing any XDG override): data, config and state."""
	home = Path.home()
	return [
		home / ".local" / "share" / "red-pill",
		home / ".local" / "share" / "neon-link",
		home / ".config" / "red-pill",
		home / ".config" / "neon-link",
		home / ".local" / "state" / "red-pill",
	]


def _is_within(path: Path, root: Path) -> bool:
	return path == root or root in path.parents


def _assert_not_production_dir(path: Path, what: str) -> None:
	"""Fail loudly if a test context resolves a storage path to a REAL production
	dir (data, config or state). This is the last line of defence: even a test
	run outside the conftest (bare `python` on a test file) cannot silently read
	the operator's config or write to production.

	Only fires when the test harness has NOT redirected storage: if the operator's
	real XDG dirs are still in effect under a test context, aborting is the
	point. When conftest has redirected XDG_* to a tmp dir, `path` will not be
	under a production dir and this is a no-op."""
	if not _is_test_context():
		return
	try:
		resolved = path.resolve()
	except Exception:
		return
	for prod in _production_dirs():
		if _is_within(resolved, prod.resolve()):
			raise RuntimeError(
				f"[TEST ISOLATION] {what} resolved to a PRODUCTION dir ({resolved}). "
				"A test is reaching the operator's real storage/config. "
				"Set XDG_DATA_HOME/XDG_CONFIG_HOME/XDG_STATE_HOME to a tmp dir (conftest does this) or pass an explicit path."
			)


def _assert_not_production_desk(path: Path, what: str) -> None:
	"""The operator's desk (${AGENT_CORE_DIR}) can live anywhere, so it cannot be
	compared against a fixed default: under a test context it must resolve to the
	temp dir or outside the real home. A desk inside the home (the real one, or
	the ghost sibling of the bunker root) means a test escaped the redirect."""
	if not _is_test_context():
		return
	import tempfile

	try:
		resolved = path.resolve()
		tmp = Path(tempfile.gettempdir()).resolve()
		home = Path.home().resolve()
	except Exception:
		return
	if _is_within(resolved, tmp) or not _is_within(resolved, home):
		return
	raise RuntimeError(
		f"[TEST ISOLATION] {what} resolved to a desk inside the operator's home ({resolved}). Set AGENT_CORE_DIR to a tmp dir (conftest does this)."
	)


def _operator_runtime_dir() -> Path:
	"""The operator's REAL runtime dir (/run/user/<uid>), deliberately computed
	without looking at XDG_RUNTIME_DIR: daemon sockets, the GPU reservations of a
	live job and bunker_state.json live there."""
	return Path("/run/user") / str(os.getuid())


def _assert_not_production_runtime(path: Path, what: str) -> None:
	"""Fail loudly if a test context resolves a RUNTIME path inside the operator's
	real /run/user/<uid>. conftest redirects XDG_RUNTIME_DIR to a tmp dir; a test
	that drops it (or points it at a dir that does not exist) used to fall back
	silently to the real runtime dir and wipe gpu_reservations.json or overwrite
	bunker_state.json."""
	if not _is_test_context() or os.name != "posix":
		return
	try:
		resolved = path.resolve()
		real = _operator_runtime_dir().resolve()
	except Exception:
		return
	if _is_within(resolved, real):
		raise RuntimeError(
			f"[TEST ISOLATION] {what} resolved to the operator's REAL runtime dir ({resolved}). Set XDG_RUNTIME_DIR to an existing tmp dir (conftest does this)."
		)


def _legacy_source_allowed(legacy_dir: Path) -> bool:
	"""Import-time legacy migrations read the operator's old dirs (~/.config/red_pill
	with the vault seed, ~/.agent). Under a test context they would copy secrets
	into — or move state out to — the test's tmp dirs: only a legacy dir inside
	the temp dir (a test's fake home) may be migrated."""
	if not _is_test_context():
		return True
	import tempfile

	try:
		return _is_within(legacy_dir.resolve(), Path(tempfile.gettempdir()).resolve())
	except Exception:
		return False


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


def get_agent_core_root() -> Path:
	"""Resuelve el desk transversal del agente (${AGENT_CORE_DIR}).

	Precedencia: env `AGENT_CORE_DIR` → registro `workspaces.yaml:agent_core`
	(fuente de verdad; sin registro, su back-compat lee la config/.env) →
	hermano `Agent_Core` del bunker_root. Los servicios systemd no exportan el
	.env: leer solo la env hacía que el Janitor cayera al hermano y creara un
	desk fantasma (`~/Documents/IA/Agent_Core`).
	"""
	path = _resolve_agent_core_root()
	_assert_not_production_desk(path, "get_agent_core_root()")
	return path


def _resolve_agent_core_root() -> Path:
	agent_core_str = os.getenv("AGENT_CORE_DIR")
	if agent_core_str:
		return Path(os.path.expanduser(agent_core_str))
	try:
		from red_pill.core.workspaces import agent_core_dir  # lazy: workspaces imports this module

		return agent_core_dir()
	except Exception as exc:
		logger.warning(f"[PATHS] workspace registry unavailable for AGENT_CORE_DIR: {exc}")
	return get_bunker_root().parent / "Agent_Core"


def get_awakening_dir(create: bool = True) -> Path:
	"""Directorio de logs de despertar autónomo (${AGENT_CORE_DIR}/awakening/).

	Rotación por despertar: cada sesión escribe su propio archivo
	`YYYYMMDD_HHMM.log` (ver `get_awakening_log_path`), coherente con la
	filosofía de carpetas del desk. El legacy `AWAKENING_LOG.md` se conserva
	como histórico y deja de crecer. `create=False` para lectores/limpiadores:
	resolver una ruta no debe fabricar directorios.
	"""
	path = get_agent_core_root() / "awakening"
	if create:
		path.mkdir(parents=True, exist_ok=True)
	return path


def get_awakening_log_path(now=None) -> Path:
	"""Ruta del log del despertar actual.

	`now` inyectable para tests (datetime). El nombre `YYYYMMDD_HHMM.log`
	codifica la sesión; cada despertar escribe en un archivo nuevo.
	"""
	import datetime

	ts = now or datetime.datetime.now()
	return get_awakening_dir() / f"{ts.strftime('%Y%m%d_%H%M')}.log"


def get_latest_awakening_log() -> Path:
	"""El log de despertar más reciente (por nombre, orden lexicográfico).

	Útil para que el worker apendee `SOVEREIGN_LOG` a la sesión viva en vez de
	a un único archivo que crece.
	"""
	awakening_dir = get_awakening_dir()
	logs = sorted(awakening_dir.glob("*.log"))
	return logs[-1] if logs else get_awakening_log_path()


def get_data_dir() -> Path:
	"""Resuelve el directorio de datos XDG base para red-pill."""
	path = Path(platformdirs.user_data_dir("red-pill"))
	_assert_not_production_dir(path, "get_data_dir()")
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


def get_log_dir() -> Path:
	"""Resuelve el directorio de logs del sistema ($XDG_STATE_HOME/red-pill/logs o fallback)."""
	try:
		path = Path(platformdirs.user_state_dir("red-pill")) / "logs"
	except AttributeError:
		path = get_data_dir() / "state" / "logs"
	_assert_not_production_dir(path, "get_log_dir()")
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_keys_dir() -> Path:
	path = get_data_dir() / "keys"
	path.mkdir(parents=True, exist_ok=True)
	# Sensitive: private keys/seeds. Enforce owner-only regardless of umask.
	try:
		os.chmod(path, 0o700)
	except OSError:
		pass
	return path


def get_unencrypted_conversations_dir() -> Path:
	path = get_data_dir() / "unencrypted_conversations"
	path.mkdir(parents=True, exist_ok=True)
	# Sensitive: plaintext conversation content. Enforce owner-only regardless of umask.
	try:
		os.chmod(path, 0o700)
	except OSError:
		pass
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


def get_config_dir() -> Path:
	"""Resuelve el directorio de configuración XDG base para red-pill."""
	path = Path(platformdirs.user_config_dir("red-pill"))
	_assert_not_production_dir(path, "get_config_dir()")
	return path


def get_neon_link_config_dir() -> Path:
	"""Resuelve el directorio de configuración XDG base para el plugin neon-link."""
	path = Path(platformdirs.user_config_dir("neon-link"))
	_assert_not_production_dir(path, "get_neon_link_config_dir()")
	return path


def get_neon_link_data_dir() -> Path:
	"""Resuelve el directorio de datos XDG base para el plugin neon-link."""
	return Path(platformdirs.user_data_dir("neon-link"))


def get_neon_link_db_path() -> Path:
	"""Resuelve la ruta a la base de datos de eventos de neon-link."""
	path = get_neon_link_data_dir() / "events.db"
	_assert_not_production_dir(path, "get_neon_link_db_path()")
	return path


def migrate_legacy_xdg_config() -> None:
	"""
	Autonomously bridges the migration from legacy underscored ~/.config/red_pill
	to the XDG-standard hyphenated ~/.config/red-pill directory.
	"""
	import logging
	import shutil
	from pathlib import Path

	logger = logging.getLogger(__name__)

	legacy_dir = Path.home() / ".config" / "red_pill"
	if not _legacy_source_allowed(legacy_dir):
		return
	target_dir = get_config_dir()

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


def resolve_llama_binary() -> Path:
	"""Resuelve la ruta absoluta del binario de llama-server, priorizando build_cuda."""
	bunker_root = get_bunker_root()
	cuda_path = bunker_root / "3rdparty" / "BitNet-1.58b" / "build_cuda" / "bin" / "llama-server"
	if cuda_path.exists():
		return cuda_path
	bitnet_path = bunker_root / "3rdparty" / "BitNet-1.58b" / "build" / "bin" / "llama-server"
	if bitnet_path.exists():
		return bitnet_path

	import shutil

	system_path = shutil.which("llama-server")
	if system_path:
		return Path(system_path)
	return cuda_path


def get_daemon_dir() -> Path:
	"""Resuelve el directorio de RUNTIME del daemon ($XDG_RUNTIME_DIR/red-pill).

	Este directorio es VOLÁTIL — se borra en cada reinicio del sistema.
	Usar SOLO para artefactos de runtime: sockets UDS, PIDs, locks.
	Para artefactos persistentes (venv, scripts), usar get_daemon_persistent_dir().
	"""
	runtime_dir = os.getenv("XDG_RUNTIME_DIR")
	if runtime_dir:
		path = Path(runtime_dir) / "red-pill"
	else:
		path = Path(platformdirs.user_cache_dir("red-pill")) / "daemons"
	_assert_not_production_runtime(path, "get_daemon_dir()")
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_daemon_persistent_dir() -> Path:
	"""Resuelve el directorio PERSISTENTE del daemon ($XDG_DATA_HOME/red-pill/daemon).

	Almacena artefactos que deben sobrevivir al reinicio del sistema:
	- .venv/ (entorno aislado con llama-cpp-python)
	- run_dual_bind.py (script del servidor dual-bind)
	- start.sh (launcher del daemon)
	- Logs de ejecución

	El socket UDS se crea en get_daemon_dir() (volátil, correcto por XDG spec).
	"""
	path = get_data_dir() / "daemon"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_model_profiles_path() -> Path:
	"""Resuelve la ruta del archivo de configuración de perfiles de modelos ($XDG_CONFIG_HOME/red-pill/model_profiles.yaml)."""
	return get_config_dir() / "model_profiles.yaml"


def get_model_runtime_path() -> Path:
	"""Ruta de la config en caliente del selector de inferencia
	($XDG_CONFIG_HOME/red-pill/model_runtime.yaml).

	RFC-HARNESS-002 §10: `default_model`, `fallup`, `hot_reload`. El fichero se
	relee por mtime en cada request (hot reload) cuando `hot_reload: true`.
	"""
	return get_config_dir() / "model_runtime.yaml"


def get_task_profiles_path() -> Path:
	"""Ruta de la zona curada de tareas ($XDG_CONFIG_HOME/red-pill/task_profiles.yaml).

	RFC-HARNESS-002 §4: conducta de tarea (prompt_file, temperature, max_tokens,
	thinking) + candidatos de modelo (referencias a model_profiles.yaml). Se
	relee por mtime en cada request cuando `hot_reload: true`.
	"""
	return get_config_dir() / "task_profiles.yaml"


def get_model_validation_path() -> Path:
	"""Ruta del registro de modelos validados ($XDG_STATE_HOME/red-pill/model_validation.json).

	RFC-HARNESS-002 §10 (K5): clave path+size+mtime+sha256_cabecera →
	{validado_at, magic, load_verified}. Cap 100, eviction por antigüedad,
	escritura atómica.
	"""
	return get_state_dir() / "model_validation.json"


def get_model_catalog_path() -> Path:
	"""Ruta del catálogo curado de modelos ($XDG_CONFIG_HOME/red-pill/model_catalog.yaml).

	Fuente de verdad de qué modelos existen y se pueden usar (RFC_TELEGRAM_RESILIENCE
	§2A/D6). Auto-seeded desde examples/model_catalog.yaml.example por el CLI si falta.
	"""
	return get_config_dir() / "model_catalog.yaml"


def get_agent_dir() -> Path:
	"""Resuelve el directorio raíz heredado/operacional del agente (~/.agent)."""
	return Path.home() / ".agent"


def get_thread_state_path() -> Path:
	"""Resuelve la ruta del archivo de estado de hilos ($XDG_DATA_HOME/red-pill/thread_state.json)."""
	return get_data_dir() / "thread_state.json"


def get_legacy_staging_dir() -> Path:
	"""Directorio de staging LEGACY ($XDG_CACHE_HOME/red-pill/staging) — solo lectura.

	La ingesta que lo consumía fue retirada (v8.0.0). Se mantiene este getter
	centralizado únicamente para el migrador (`scripts/migrate_single_writer.py`),
	que archiva el staging residual de instalaciones previas. NO se crea.
	"""
	return Path(platformdirs.user_cache_dir("red-pill")) / "staging"


def get_ingestion_dir() -> Path:
	"""Resuelve el directorio por defecto de ingesta de archivos ($XDG_DATA_HOME/red-pill/ingestion)."""
	path = get_data_dir() / "ingestion"
	path.mkdir(parents=True, exist_ok=True)
	return path


def get_antigravity_root() -> Path:
	"""
	Resuelve el directorio raíz del IDE Antigravity.

	Orden de precedencia:
	1. $ANTIGRAVITY_ROOT (explícita override)
	2. ~/.gemini/antigravity (convención estándar)
	"""
	override = os.getenv("ANTIGRAVITY_ROOT")
	if override:
		return Path(override)
	return Path.home() / ".gemini" / "antigravity"


def get_antigravity_brain_dir() -> Path:
	"""Resuelve el directorio de conversaciones del IDE Antigravity (brain/)."""
	override = os.getenv("ANTIGRAVITY_BRAIN_PATH")
	if override:
		return Path(override)
	return get_antigravity_root() / "brain"


def get_antigravity_rules_dir() -> Path:
	"""Resuelve el directorio de rules del IDE Antigravity (rules/)."""
	return get_antigravity_root() / "rules"


def get_antigravity_conversations_dir() -> Path:
	"""Resuelve el directorio legacy de conversaciones CLI (conversations/)."""
	return get_antigravity_root() / "conversations"


def get_antigravity_conversations_export_dir() -> Path:
	"""Directorio del export manual congelado del 23-mar-2026 (47 MD, era temprana).

	No es una ruta viva del IDE — es un snapshot histórico para la fuente
	``antigravity_export``. Respeta ``ANTIGRAVITY_ROOT`` al derivar de
	``get_antigravity_root()``.
	"""
	return get_antigravity_root() / "conversations_export"


def get_swarm_config_path() -> Path:
	"""Resuelve la ruta del archivo de comunidades swarm ($XDG_CONFIG_HOME/red-pill/swarm_communities.json)."""
	return get_config_dir() / "swarm_communities.json"


def migrate_legacy_agent_dirs() -> None:
	"""
	Autonomously migrates operational databases and state from ~/.agent/
	to their new standard XDG locations.
	"""
	import shutil

	legacy_agent = Path.home() / ".agent"
	if not _legacy_source_allowed(legacy_agent) or not legacy_agent.exists() or not legacy_agent.is_dir():
		return

	# Define migration map: (source, target)
	migration_map = [
		(legacy_agent / "thread_state.json", get_thread_state_path()),
		(legacy_agent / "ingestion", get_ingestion_dir()),
		(legacy_agent / "config" / "swarm_communities.json", get_swarm_config_path()),
		(legacy_agent / "model_profiles.yaml", get_model_profiles_path()),
		(legacy_agent / "auditor_cache.json", get_data_dir() / "auditor_cache.json"),
		(legacy_agent / "auditor_journal_cursor", get_data_dir() / "auditor_journal_cursor"),
		(legacy_agent / "bunker_persona_cache.json", get_data_dir() / "bunker_persona_cache.json"),
		(legacy_agent / "chronicle_processed.json", get_data_dir() / "chronicle_processed.json"),
		(legacy_agent / "chronicle_processed.json.bak", get_data_dir() / "chronicle_processed.json.bak"),
		(legacy_agent / ".pending_swagger_messages.json", get_data_dir() / ".pending_swagger_messages.json"),
		(legacy_agent / "keys", get_keys_dir()),
	]

	for src, dst in migration_map:
		if src.exists():
			# The dir getters above (get_keys_dir/get_staging_dir/…) mkdir on evaluation, so a
			# directory dst always "exists" but may be empty. Treat empty-dir as absent so real
			# legacy data is migrated, never rmtree'd unmigrated.
			dst_has_data = dst.exists() and (dst.is_file() or any(dst.iterdir()))
			if dst_has_data:
				# If target already exists WITH data, skip to prevent overwriting newer state
				# but delete the legacy source to keep ~/.agent clean
				try:
					if src.is_dir():
						shutil.rmtree(src)
					else:
						src.unlink()
				except Exception as e:
					logger.error(f"[XDG-MIGRATION] Failed to clean up redundant legacy {src.name}: {e}")
				continue

			logger.info(f"[XDG-MIGRATION] Moving operational asset {src} -> {dst}")
			try:
				# Ensure target parent dir exists
				dst.parent.mkdir(parents=True, exist_ok=True)
				# Remove an empty dst dir the getters pre-created, so move lands src AT dst
				# rather than nesting it inside (dst/src_basename).
				if dst.is_dir() and not any(dst.iterdir()):
					dst.rmdir()
				shutil.move(str(src), str(dst))
			except Exception as e:
				logger.error(f"[XDG-MIGRATION] Failed to move {src.name}: {e}")


# Run migrations on import to guarantee self-healing/boot-time compliance
try:
	migrate_legacy_xdg_config()
	migrate_legacy_agent_dirs()
except Exception as _e:
	logger.error(f"[PATHS] Failed to run path migrations: {_e}")
