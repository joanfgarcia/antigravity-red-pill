import logging
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.core.paths import get_awakening_dir
from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

# Cada despertar escribe su propio `YYYYMMDD_HHMM.log` (hora local, ver
# get_awakening_log_path). La fecha va en el nombre, así que se usa ESA para la
# edad — no el mtime, que `git` puede tocar al restaurar/mover el desk.
_AWAKENING_LOG_RE = re.compile(r"^(\d{8})_\d{4}\.log$")

# El desk es un repo git y los despertares commitean sus logs: tras borrarlos se
# deja la baja en el índice para que el siguiente commit del desk la registre.
_GIT_TIMEOUT_S = 15
_GIT_CHUNK = 200
# Variables que redirigirían git a OTRO repo/índice si el Janitor las heredara.
_GIT_REDIRECT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


class AwakeningLogsPlugin(JanitorPlugin):
	"""Purga los logs de despertar más antiguos que `days_to_keep`.

	No "rota" (los logs ya están rotados por despertar): borra los que superan
	el TTL. Configurable en `plugins.awakening_logs.days_to_keep`; default 30
	días, comparando FECHAS: se borra si `fecha del nombre < hoy - days_to_keep`.
	Solo toca ficheros `YYYYMMDD_HHMM.log`; nunca `notes/`, `done/` ni
	`README.md`. Si el directorio vive en un work tree git (el desk lo es), la
	baja se deja preparada en el índice (`git rm --cached`) para que el próximo
	commit del desk la recoja en vez de quedar `D` sin preparar cada noche.
	"""

	@property
	def name(self) -> str:
		return "awakening_logs"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running awakening_logs plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days_to_keep = int(plugin_cfg.get("days_to_keep", 30))

		awakening_dir = get_awakening_dir(create=False)
		if not awakening_dir.is_dir():
			janitor.log(f"[Janitor] Awakening dir {awakening_dir} not found. Skipping.")
			return {"awakening_logs_purged": 0}

		cutoff = datetime.now().date() - timedelta(days=days_to_keep)
		deleted: List[str] = []
		for item in sorted(awakening_dir.glob("*.log")):
			day = self._log_date(item)
			if day is None or day >= cutoff:
				continue
			try:
				item.unlink()
				deleted.append(item.name)
				janitor.log(f"[Janitor] Deleted old awakening log: {item.name}")
			except Exception as e:
				logger.error(f"[Janitor] Failed to delete awakening log {item}: {e}")

		if deleted:
			janitor.log(f"[Janitor] awakening_logs: {len(deleted)} log(s) older than {days_to_keep}d purged.")
			_stage_git_deletions(awakening_dir, deleted, janitor)
		return {"awakening_logs_purged": len(deleted)}

	def _log_date(self, path: Path) -> Optional[date]:
		"""Fecha codificada en el nombre; None (= no se toca) si no sigue el esquema."""
		match = _AWAKENING_LOG_RE.match(path.name)
		if not match:
			return None
		try:
			return datetime.strptime(match.group(1), "%Y%m%d").date()
		except ValueError:
			return None


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess:
	env = {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECT_ENV}
	return subprocess.run(
		["git", "-C", str(directory), *args],
		capture_output=True,
		text=True,
		timeout=_GIT_TIMEOUT_S,
		env=env,
		check=False,
	)


def _stage_git_deletions(directory: Path, names: List[str], janitor: Any) -> None:
	"""Prepara en el índice la baja de `names` si `directory` está en un work tree git.

	`git rm --cached --ignore-unmatch`: los que no estaban trackeados se ignoran.
	Nunca lanza: sin git, fuera de un repo, con el índice bloqueado o por timeout
	solo deja constancia en el log (la baja seguirá pendiente para `git add -A`).
	"""
	try:
		probe = _git(directory, "rev-parse", "--is-inside-work-tree")
		if probe.returncode != 0 or probe.stdout.strip() != "true":
			logger.debug(f"[Janitor] awakening_logs: {directory} no está en un work tree git; nada que preparar.")
			return
		for i in range(0, len(names), _GIT_CHUNK):
			res = _git(directory, "rm", "--cached", "--quiet", "--ignore-unmatch", "--", *names[i : i + _GIT_CHUNK])
			if res.returncode != 0:
				logger.warning(f"[Janitor] awakening_logs: git rm --cached falló ({res.returncode}): {res.stderr.strip()[:300]}")
				return
		janitor.log(f"[Janitor] awakening_logs: baja de {len(names)} log(s) preparada en el índice git del desk.")
	except Exception as e:
		logger.warning(f"[Janitor] awakening_logs: no se pudo preparar la baja en git: {e}")
