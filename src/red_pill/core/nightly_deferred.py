"""Contador de diferidos por techo — lo diferido vuelve PRIMERO (NB-001 F3.2, D-NB-16).

Por qué existe
--------------
El techo de un compuesto difiere las instancias de fan-out que no llegaron a
arrancar (`JobDeferred("budget_exhausted")`). Vuelven «la noche siguiente»
porque cada noche es un job NUEVO que re-deriva el árbol desde `discover`, pero
eso no garantiza que vuelvan *pronto*: la selección ordena stale-first y
`stale-first` **no ordena por edad**, así que la misma sesión monstruo puede
volver a ganar el sitio y dejar a la misma pequeña fuera otra noche más. Sin
contador no hay forma de distinguir «diferida una vez» de «diferida cinco
noches seguidas».

Decisión del Operador (2026-11-15, D-NB-16): lo diferido se trata **primero**,
con orden `noches desc · coste asc · stale-first`. El desempate por coste no es
un adorno: la selección corta con `break` en el primer desbordamiento, así que
**el orden decide quién queda fuera**; sin él, «primero» sería «el monstruo otra
vez».

Por qué el estado vive aquí y no en el checkpoint del job
--------------------------------------------------------
Cada noche es un job nuevo (`nightly_cloud_backup.sh` → `job submit --recipe
nightly.yaml --singleton`): el checkpoint no cruza de una noche a otra, y la
ruta de la instancia (`.../memento-distill-4`) se recalcula cada noche — el
índice apuntaría a otra sesión. La clave es la **unidad de fan-out**
(`source:session`), que sí es estable entre noches.

Contrato
--------
- `record(units, stage=…)`: suma una noche a cada unidad (crea la entrada si no estaba).
- `clear(units)`: la unidad se procesó — fuera del contador.
- `load()`: entradas vigentes, retirando las que llevan más de `RETAIN_S` sin volver a diferirse (una unidad que dejó de estar pendiente no puede quedarse en el libro para siempre).
- Escritura atómica con `flock` + `tmp` + `os.replace`: el driver y la selección corren en procesos distintos y pueden coincidir.
- **Nunca lanza**: un fallo del libro no puede tumbar la noche. Best-effort al escribir, fail-open al leer (sin libro → orden de siempre).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from red_pill.core.paths import get_state_dir

logger = logging.getLogger(__name__)

FILENAME = "nightly_deferred.json"
LOCKNAME = "nightly_deferred.lock"
# Una unidad que no se ha vuelto a diferir en dos noches ya no está «diferida»:
# o se procesó, o salió de la cola. Se retira para no arrastrar fantasmas.
RETAIN_S = 2 * 86400.0


def path():
	"""`${STATE_DIR}/nightly_deferred.json`."""
	return get_state_dir() / FILENAME


def normalize_unit(item: Any) -> str:
	"""`source:session` como clave estable.

	El fan-out arrastra la unidad de dos formas según quién la escriba: el
	reporte del `discover` la emite como trío `(source, session_id, reason)` y el
	checkpoint la guarda ya unida. Aquí se aceptan las dos: si viene en lista o
	tupla, se une con `:`; si viene en texto, se respeta.
	"""
	if item is None:
		return ""
	if isinstance(item, (list, tuple)):
		parts = [str(p) for p in item[:2] if p is not None]
		return ":".join(parts) if parts else ""
	return str(item).strip()


def unit_key(source: str, session_id: str) -> str:
	"""Clave de la unidad tal como la escribe el fan-out (`source:session`)."""
	return normalize_unit((source, session_id))


def _read() -> Dict[str, Any]:
	try:
		raw = json.loads(path().read_text(encoding="utf-8"))
	except (OSError, ValueError, TypeError):
		return {"units": {}}
	if not isinstance(raw, dict):
		return {"units": {}}
	if not isinstance(raw.get("units"), dict):
		raw["units"] = {}
	return raw


def _prune(units: Dict[str, Any], now: float) -> None:
	for key in list(units):
		try:
			last = float((units.get(key) or {}).get("last_deferred_at") or 0.0)
		except (TypeError, ValueError):
			last = 0.0
		if last <= 0.0 or (now - last) > RETAIN_S:
			units.pop(key, None)


def _write(data: Dict[str, Any]) -> None:
	directorio = get_state_dir()
	directorio.mkdir(parents=True, exist_ok=True)
	fd, tmp = tempfile.mkstemp(dir=str(directorio), prefix=".nightly_deferred.", suffix=".tmp")
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as fh:
			fh.write(json.dumps(data, ensure_ascii=False, indent=1))
		os.replace(tmp, path())
	finally:
		if os.path.exists(tmp):
			os.unlink(tmp)


def _update(mutate: Callable[[Dict[str, Any]], None]) -> None:
	"""Lee-modifica-escribe bajo lock. Best-effort: nunca propaga el error."""
	directorio = get_state_dir()
	try:
		directorio.mkdir(parents=True, exist_ok=True)
		with open(directorio / LOCKNAME, "w", encoding="utf-8") as lock:
			fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
			try:
				data = _read()
				mutate(data["units"])
				now = time.time()
				_prune(data["units"], now)
				data["updated_at"] = now
				_write(data)
			finally:
				fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
	except Exception as exc:  # noqa: BLE001 — el libro no puede tumbar la noche
		logger.debug(f"[nightly_deferred] escritura no aplicada: {exc}")


def load(now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
	"""Unidades vigentes: `{clave: {nights, first_deferred_at, last_deferred_at, stage}}`."""
	units = dict(_read().get("units") or {})
	_prune(units, float(now if now is not None else time.time()))
	return {str(k): dict(v or {}) for k, v in units.items() if isinstance(v, dict)}


def record(units: Iterable[Any], *, stage: str = "") -> None:
	"""Suma una noche diferida a cada unidad. `stage` es informativo (trazabilidad)."""
	keys: List[str] = [k for k in (normalize_unit(u) for u in units) if k]
	if not keys:
		return
	now = time.time()

	def _m(units_map: Dict[str, Any]) -> None:
		for key in keys:
			entry = dict(units_map.get(key) or {})
			entry["nights"] = int(entry.get("nights") or 0) + 1
			entry["first_deferred_at"] = float(entry.get("first_deferred_at") or now)
			entry["last_deferred_at"] = now
			if stage:
				entry["stage"] = stage
			units_map[key] = entry

	_update(_m)


def clear(units: Iterable[Any]) -> None:
	"""La unidad se procesó: sale del libro (si estaba)."""
	keys = [k for k in (normalize_unit(u) for u in units) if k]
	if not keys:
		return

	def _m(units_map: Dict[str, Any]) -> None:
		for key in keys:
			units_map.pop(key, None)

	_update(_m)


def nights(ledger: Dict[str, Dict[str, Any]], key: str) -> int:
	"""Noches que lleva diferida una unidad según el libro (0 si no está)."""
	try:
		return int((ledger.get(key) or {}).get("nights") or 0)
	except (TypeError, ValueError):
		return 0


def summary(ledger: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, int]:
	"""`{clave: noches}` de lo que está diferido ahora mismo (para el resultado/tablón)."""
	datos = load() if ledger is None else ledger
	out: Dict[str, int] = {}
	for key, entry in datos.items():
		count = nights(datos, key)
		if count > 0:
			out[key] = count
	return out
