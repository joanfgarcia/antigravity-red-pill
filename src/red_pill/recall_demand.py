"""MEM-012 · F3 — tasa de abstención y registro de demanda.

Dos artefactos en el state dir, ambos locales y sin contenido sensible:

- `recall_abstention_stats.json` — contadores: recalls totales, cuántos se
	abstuvieron, por colección y por banda. La **tasa** sale de aquí.
- `recall_demand.jsonl` — una línea por consulta que **no encontró** lo que
	pedía: la lista de lo que falta por recordar. Solo se escribe cuando
	`no_recall` es cierto (el resto ya está en memoria).

La consulta se pasa por `scrub_secrets` y se recorta: el registro sirve para
saber **qué falta**, no para coleccionar texto del Operador. Se puede apagar con
`SW_RECALL_DEMAND_LOG_ENABLED=false`; un fallo de escritura nunca rompe el
recall (el llamante lo envuelve, y aquí también se falla en silencio).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

STATS_FILE = "recall_abstention_stats.json"
DEMAND_FILE = "recall_demand.jsonl"
LOCK_FILE = "recall_abstention.lock"


def _state_dir(state_dir: Optional[Any] = None) -> Path:
	if state_dir is not None:
		path = Path(state_dir)
		path.mkdir(parents=True, exist_ok=True)
		return path
	from red_pill.core.paths import get_state_dir

	return get_state_dir()


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
	"""Exclusión entre procesos (dos servidores MCP pueden escribir a la vez)."""
	with open(path, "a+") as handle:
		try:
			import fcntl

			fcntl.flock(handle, fcntl.LOCK_EX)
			yield
		finally:
			try:
				import fcntl

				fcntl.flock(handle, fcntl.LOCK_UN)
			except Exception:
				pass


def _empty_stats() -> Dict[str, Any]:
	return {
		"total": 0,
		"no_recall": 0,
		"below_floor_total": 0,
		"by_collection": {},
		"by_confidence": {},
		"updated": 0.0,
	}


def load_stats(state_dir: Optional[Any] = None) -> Dict[str, Any]:
	path = _state_dir(state_dir) / STATS_FILE
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
		if isinstance(data, dict):
			return {**_empty_stats(), **data}
	except (OSError, ValueError):
		pass
	return _empty_stats()


def load_demand(limit: int = 20, state_dir: Optional[Any] = None) -> List[Dict[str, Any]]:
	path = _state_dir(state_dir) / DEMAND_FILE
	lines: List[str] = []
	try:
		with path.open("r", encoding="utf-8") as handle:
			lines = handle.readlines()
	except OSError:
		return []
	out: List[Dict[str, Any]] = []
	for line in lines[-max(1, limit) :]:
		try:
			out.append(json.loads(line))
		except ValueError:
			continue
	return out


def _sanitize(query: str, max_chars: int) -> str:
	from red_pill.memento.scrub import scrub_secrets

	text = " ".join(str(query or "").split())
	return scrub_secrets(text)[: max(1, max_chars)]


def record_recall(
	*,
	query: str,
	collection: str,
	confidence: str,
	no_recall: bool,
	max_similarity: float = 0.0,
	below_floor_count: int = 0,
	caller: str = "",
	enabled: Optional[bool] = None,
	max_chars: Optional[int] = None,
	state_dir: Optional[Any] = None,
) -> bool:
	"""Anota una consulta. Devuelve True si escribió (para tests); nunca lanza."""
	try:
		import red_pill.config as cfg

		if enabled is None:
			enabled = bool(getattr(cfg, "SW_RECALL_DEMAND_LOG_ENABLED", True))
		if not enabled:
			return False
		if max_chars is None:
			max_chars = int(getattr(cfg, "SW_RECALL_DEMAND_MAX_CHARS", 240) or 240)

		base = _state_dir(state_dir)
		now = time.time()
		with _locked(base / LOCK_FILE):
			stats = load_stats(base)
			stats["total"] = int(stats.get("total", 0)) + 1
			stats["no_recall"] = int(stats.get("no_recall", 0)) + (1 if no_recall else 0)
			stats["below_floor_total"] = int(stats.get("below_floor_total", 0)) + max(0, int(below_floor_count))
			by_collection = stats.setdefault("by_collection", {})
			bucket = by_collection.setdefault(collection, {"total": 0, "no_recall": 0})
			bucket["total"] = int(bucket.get("total", 0)) + 1
			bucket["no_recall"] = int(bucket.get("no_recall", 0)) + (1 if no_recall else 0)
			by_confidence = stats.setdefault("by_confidence", {})
			by_confidence[confidence] = int(by_confidence.get(confidence, 0)) + 1
			stats["updated"] = now
			tmp = base / f"{STATS_FILE}.tmp"
			tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
			os.replace(tmp, base / STATS_FILE)

			if no_recall:
				entry = {
					"ts": round(now, 3),
					"collection": collection,
					"confidence": confidence,
					"max_similarity": round(float(max_similarity), 4),
					"below_floor_count": int(below_floor_count),
					"caller": caller,
					"query": _sanitize(query, max_chars),
				}
				with (base / DEMAND_FILE).open("a", encoding="utf-8") as handle:
					handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
		return True
	except Exception:
		return False


def abstention_rate(stats: Dict[str, Any]) -> Optional[float]:
	"""Fracción de consultas que se abstuvieron, o None si no hay muestra."""
	total = int(stats.get("total", 0) or 0)
	if total <= 0:
		return None
	return round(int(stats.get("no_recall", 0) or 0) / total, 4)
