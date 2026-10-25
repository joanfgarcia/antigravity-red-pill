"""Retención de artefactos de estado (B-01h / S5).

El journal externo (`state/external_turns/archive`) y los resultados de jobs
(`state/jobs/results`) crecen un fichero por turno/job. El espejo canónico ya
guarda la historia; estos ficheros son auditoría operativa, no la fuente de
verdad. Política conservadora:

- Nunca toca `external_turns/current` (turno en vuelo).
- Un `result` de un job no terminal (PENDING/PROCESSING/PAUSED/FRUSTRATED…)
  se conserva: puede reanudarse.
- Conserva los N `result` más recientes por misión (default 1).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

# Solo los jobs cerrados con éxito son elegibles. FRUSTRATED/BLOCKED/PAUSED
# pueden reanudarse; su result se conserva como evidencia.
_TERMINAL_OK = {"COMPLETED"}


def _read_json(path: Path) -> Dict[str, Any]:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _completed_at(data: Dict[str, Any], path: Path) -> float:
	try:
		return float(data.get("completed_at") or path.stat().st_mtime)
	except Exception:
		try:
			return path.stat().st_mtime
		except OSError:
			return 0.0


def _unlink(path: Path) -> int:
	try:
		size = path.stat().st_size
		path.unlink()
		return size
	except Exception as e:  # noqa: BLE001
		logger.error(f"[Janitor] Failed to delete {path}: {e}")
		return 0


class StateArtifactsPurgePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "state_artifacts_purge"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		from red_pill.core.paths import get_state_dir

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days = float(plugin_cfg.get("days_to_keep", 30))
		keep_per_mission = max(0, int(plugin_cfg.get("jobs_results_keep_per_mission", 1)))
		state = get_state_dir()
		cutoff = datetime.now().timestamp() - (days * 86400)

		janitor.log(f"[Janitor] Running state_artifacts_purge (retention={days}d)...")

		# 1) Journal externo: solo el archivo; `current/` es el turno en vuelo.
		journal_purged = 0
		journal_bytes = 0
		archive = state / "external_turns" / "archive"
		if archive.is_dir():
			for path in archive.glob("*.json"):
				try:
					if path.stat().st_mtime >= cutoff:
						continue
				except OSError:
					continue
				journal_bytes += _unlink(path)
				journal_purged += 1

		# 2) Resultados de jobs: solo jobs cerrados y conservando N por misión.
		results_purged = 0
		results_kept = 0
		results_skipped_active = 0
		results_bytes = 0
		results_dir = state / "jobs" / "results"
		if results_dir.is_dir():
			qm = None
			try:
				from red_pill.cognitive.queue_manager import CognitiveQueueManager

				qm = CognitiveQueueManager()
			except Exception as e:  # noqa: BLE001
				logger.warning(f"[Janitor] state_artifacts_purge: queue unavailable ({e}); results intactos")

			if qm is not None:
				eligible: List[Tuple[Path, Dict[str, Any]]] = []
				for path in results_dir.glob("*.json"):
					try:
						if path.stat().st_mtime >= cutoff:
							continue
					except OSError:
						continue
					data = _read_json(path)
					job_id = str(data.get("job_id") or path.stem)
					try:
						task = qm.get_task(job_id) or {}
						status = str(task.get("status") or "").upper()
					except Exception as e:  # noqa: BLE001
						logger.warning(f"[Janitor] state_artifacts_purge: status({job_id}) failed ({e}); se conserva")
						results_skipped_active += 1
						continue
					if status and status not in _TERMINAL_OK:
						results_skipped_active += 1
						continue
					eligible.append((path, data))

				# Más recientes primero: los N primeros de cada misión se quedan.
				eligible.sort(key=lambda item: _completed_at(item[1], item[0]), reverse=True)
				kept_by_mission: Dict[str, int] = {}
				for path, data in eligible:
					mission = str(data.get("mission_id") or "unknown")
					kept = kept_by_mission.get(mission, 0)
					if kept < keep_per_mission:
						kept_by_mission[mission] = kept + 1
						results_kept += 1
						continue
					results_bytes += _unlink(path)
					results_purged += 1

		metrics = {
			"state_artifacts_retention_days": int(days),
			"journal_archived_purged": journal_purged,
			"journal_archived_bytes_freed": journal_bytes,
			"job_results_purged": results_purged,
			"job_results_bytes_freed": results_bytes,
			"job_results_kept_per_mission": keep_per_mission,
			"job_results_kept": results_kept,
			"job_results_skipped_active": results_skipped_active,
		}
		janitor.log(f"[Janitor] state_artifacts_purge: {json.dumps(metrics, ensure_ascii=False)}")
		return metrics
