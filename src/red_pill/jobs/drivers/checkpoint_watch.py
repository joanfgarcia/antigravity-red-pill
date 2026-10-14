"""Checkpoint watcher for script_job: measures how often the satellite actually
persists recoverable progress while a step runs. Extracted from `script.py`
(SHARD-PS-04) — self-contained, only depends on base logging helpers.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.jobs.drivers.base import append_job_log, human_duration


class _CheckpointWatcher:
	"""Vigila el fichero de checkpoint MIENTRAS corre el step.

	La granularidad que importa no es cuánto vive el proceso, sino cada cuánto
	deja algo registrado: eso es lo que se pierde al interrumpirlo y desde donde
	se retoma. Un step puede contener varios guardados, así que medirlo por el
	mtime de antes y después lo inflaría hasta la duración del step entero.
	Aquí se observa cada escritura, con su intervalo real.
	"""

	def __init__(self, state_path: Optional[Path], job_id: str, poll_seconds: float = 1.0):
		self._state_path = state_path
		self._job_id = job_id
		self._poll = poll_seconds
		self._stop = threading.Event()
		self._thread: Optional[threading.Thread] = None
		self._last_mtime: Optional[float] = None
		self._last_seen: float = 0.0
		self.intervals: List[float] = []
		self.writes: int = 0

	def __enter__(self) -> "_CheckpointWatcher":
		self._last_mtime = self._current_mtime()
		self._last_seen = time.time()
		if self._state_path is not None:
			self._thread = threading.Thread(target=self._watch, name="rp-checkpoint-watch", daemon=True)
			self._thread.start()
		return self

	def __exit__(self, *exc: Any) -> None:
		self._stop.set()
		if self._thread:
			self._thread.join(timeout=max(2.0, self._poll * 2))
		# Última mirada: el guardado más importante es el del final de la época, y
		# el proceso sale acto seguido — entre el último sondeo y su muerte cabe
		# justo esa escritura. Sin este cierre, se perdería la que más importa.
		self._check_once()

	def _watch(self) -> None:
		while not self._stop.wait(self._poll):
			self._check_once()

	def _check_once(self) -> None:
		mtime = self._current_mtime()
		if mtime is None or mtime == self._last_mtime:
			return
		now = time.time()
		if self._last_mtime is not None:
			self.intervals.append(now - self._last_seen)
		self.writes += 1
		note = f" (+{human_duration(self.intervals[-1])} desde el anterior)" if self.intervals else " (primero observado en este step)"
		append_job_log(self._job_id, f"checkpoint escrito por el satélite{note}")
		self._last_mtime, self._last_seen = mtime, now

	def _current_mtime(self) -> Optional[float]:
		try:
			return self._state_path.stat().st_mtime if self._state_path and self._state_path.exists() else None
		except OSError:
			return None


def _dig(data: Dict[str, Any], key_path: str) -> Any:
	"""Lee una clave declarativa del checkpoint, con soporte de ruta `a.b.c`."""
	node: Any = data
	for part in str(key_path).split("."):
		if not isinstance(node, dict) or part not in node:
			return None
		node = node[part]
	return node
