"""Purga del scratch de los arneses fuera del STATE_DIR (p. ej. `/tmp/opencode`).

El `scratch_purge` clásico solo limpia `${RP_TMP_DIR}/scratch` (`~/tmp/scratch`).
Los arneses usan otros directorios efímeros que el sistema solo limpia al
reiniciar; con automatización crecen sin control. Este plugin borra **hijos**
con `mtime` mayor que `days_to_keep` y nunca el directorio configurado.

Es opt-in: `paths` vacío (seed) = no-op. La instalación decide qué rutas limpiar.
Guardas: no sigue symlinks y rechaza `/` y `$HOME`.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


def _size(path: Path) -> int:
	try:
		if path.is_symlink() or path.is_file():
			return path.lstat().st_size
		return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
	except Exception:  # noqa: BLE001
		return 0


def _delete(path: Path) -> None:
	if path.is_symlink() or path.is_file():
		path.unlink()
	elif path.is_dir():
		shutil.rmtree(path)


class HarnessScratchPurgePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "harness_scratch_purge"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days = float(plugin_cfg.get("days_to_keep", 14))
		raw_paths = plugin_cfg.get("paths") or []
		if isinstance(raw_paths, str):
			raw_paths = [raw_paths]
		paths: List[Path] = [Path(str(p)).expanduser() for p in raw_paths if str(p).strip()]
		cutoff = datetime.now().timestamp() - (days * 86400)

		janitor.log(f"[Janitor] Running harness_scratch_purge (retention={days}d, paths={len(paths)})...")

		purged = 0
		freed = 0
		scanned = 0
		guarded = {Path("/").resolve(), Path.home().resolve()}
		for path in paths:
			if path.is_symlink() or not path.is_dir():
				logger.warning(f"[Janitor] harness_scratch_purge: {path} no es un directorio real; skip")
				continue
			if path.resolve() in guarded:
				logger.warning(f"[Janitor] harness_scratch_purge: {path} es raíz/HOME; skip")
				continue
			try:
				entries = list(path.iterdir())
			except OSError as e:
				logger.error(f"[Janitor] harness_scratch_purge: no puedo leer {path}: {e}")
				continue
			for entry in entries:
				scanned += 1
				try:
					if entry.stat().st_mtime >= cutoff:
						continue
					size = _size(entry)
					_delete(entry)
					purged += 1
					freed += size
					janitor.log(f"[Janitor] Purged harness scratch: {entry.name}")
				except Exception as e:  # noqa: BLE001
					logger.error(f"[Janitor] Failed to purge {entry}: {e}")

		metrics = {
			"harness_scratch_retention_days": int(days),
			"harness_scratch_paths": [str(p) for p in paths],
			"harness_scratch_scanned": scanned,
			"harness_scratch_purged": purged,
			"harness_scratch_bytes_freed": freed,
		}
		janitor.log(f"[Janitor] harness_scratch_purge: {json.dumps(metrics, ensure_ascii=False)}")
		return metrics
