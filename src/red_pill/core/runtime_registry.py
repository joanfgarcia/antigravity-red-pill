"""runtime_registry — registro de engines de inferencia local (RFC-HARNESS-003).

Los perfiles de modelo (`model_profiles.yaml`) declaran QUÉ se ejecuta; este
registro declara CON QUÉ: cada runtime describe el binario (cli/server), su
linaje (`kind`), versión y capacidades (tipos de quant soportados, quirks de
build). Ausencia de `runtime` en un perfil = runtime por defecto
(`default_runtime` del registro o `llama_cpp_stock`).

Filosofía anti-fallback-silencioso: un runtime declarado pero no disponible
NO cae al stock (el modo de fallo peligroso: `Q2_0` ternario en stock produce
basura sin warning) — `require()` levanta `RuntimeUnavailableError` con motivo.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from red_pill.core.paths import get_bunker_root, get_runtimes_path

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_ID = "llama_cpp_stock"


class RuntimeUnavailableError(RuntimeError):
	"""Runtime declarado por un perfil que no está instalado/operativo."""


class RuntimeRegistry:
	_runtimes_cache: Optional[Dict[str, dict]] = None
	_default_runtime: Optional[str] = None
	_runtimes_mtime: float = 0.0

	@classmethod
	def reload(cls) -> None:
		"""Recarga si el mtime de runtimes.yaml cambió (hot reload, patrón ModelRegistry)."""
		try:
			mtime = os.stat(get_runtimes_path()).st_mtime
		except OSError:
			return
		if cls._runtimes_cache is not None and abs(mtime - cls._runtimes_mtime) < 1e-6:
			return
		cls._runtimes_cache = None
		cls._load()
		cls._runtimes_mtime = mtime

	@classmethod
	def get(cls, runtime_id: str) -> dict:
		"""Runtime por id, con `binary`/`server` resueltos a rutas absolutas."""
		if cls._runtimes_cache is None:
			cls._load()
		raw = (cls._runtimes_cache or {}).get(runtime_id)
		if raw is None:
			return {}
		resolved = cls._resolve_paths(dict(raw))
		resolved.setdefault("id", runtime_id)
		return resolved

	@classmethod
	def all(cls) -> Dict[str, dict]:
		"""Todos los runtimes declarados, con rutas resueltas."""
		if cls._runtimes_cache is None:
			cls._load()
		return {rid: cls._resolve_paths(dict(rt)) for rid, rt in (cls._runtimes_cache or {}).items()}

	@classmethod
	def default_id(cls) -> str:
		if cls._runtimes_cache is None:
			cls._load()
		return cls._default_runtime or DEFAULT_RUNTIME_ID

	@classmethod
	def for_profile(cls, profile: dict) -> dict:
		"""Runtime declarado por un perfil (o el default si no declara `runtime`)."""
		runtime_id = (profile or {}).get("runtime") or cls.default_id()
		return cls.get(runtime_id)

	@classmethod
	def check_available(cls, runtime_id: str) -> Tuple[bool, str]:
		"""¿Binario presente y ejecutable? Devuelve (ok, motivo)."""
		rt = cls.get(runtime_id)
		if not rt:
			return False, f"runtime '{runtime_id}' no declarado en {get_runtimes_path()}"
		binary = rt.get("binary") or rt.get("server")
		if not binary:
			return False, f"runtime '{runtime_id}' sin 'binary'/'server'"
		path = Path(binary)
		if not path.exists():
			return False, f"binario no existe: {binary}"
		if not os.access(path, os.X_OK):
			return False, f"binario no ejecutable: {binary}"
		return True, ""

	@classmethod
	def require(cls, runtime_id: str) -> dict:
		"""Runtime obligatorio: o está operativo, o se falla limpio (nunca stock por accidente)."""
		ok, reason = cls.check_available(runtime_id)
		if not ok:
			raise RuntimeUnavailableError(
				f"[RUNTIME] {reason}. Instala/compila el engine o corrige '{get_runtimes_path()}'."
			)
		return cls.get(runtime_id)

	@classmethod
	def _resolve_paths(cls, rt: dict) -> dict:
		"""`binary`/`server`/`library` relativos → absolutos contra el bunker root; `~` expandido."""
		for key in ("binary", "server", "library"):
			value = rt.get(key)
			if isinstance(value, str) and value:
				rt[key] = str(_expand(value))
		return rt

	@classmethod
	def _load(cls) -> None:
		config_path = get_runtimes_path()
		seed_path = os.path.join(get_bunker_root(), "examples", "runtimes.yaml.example")

		# Auto-seed if missing (patrón ModelRegistry: instalación fresca sin registro).
		if not config_path.exists() and os.path.exists(seed_path):
			try:
				config_path.parent.mkdir(parents=True, exist_ok=True)
				shutil.copy2(seed_path, config_path)
				logger.info(f"Seeded runtimes registry to {config_path}")
			except Exception as e:
				logger.error(f"Failed to seed runtimes registry: {e}")

		cls._runtimes_cache = {}
		cls._default_runtime = None
		if config_path.exists():
			try:
				with open(config_path, "r", encoding="utf-8") as f:
					data = yaml.safe_load(f) or {}
				if isinstance(data, dict):
					cls._runtimes_cache = data.get("runtimes") or {}
					cls._default_runtime = data.get("default_runtime")
			except Exception as e:
				logger.error(f"Failed to load runtimes from {config_path}: {e}")


def _expand(value: str) -> Path:
	path = Path(os.path.expanduser(value))
	if not path.is_absolute():
		path = get_bunker_root() / path
	return path
