"""La escalera del olvido (RFC-OLV-001, F3) — **política, no parámetro**.

Una sola ruta decide olvidar, y decide en **días activos**: días en los que hubo
actividad real, nunca días de calendario. La ausencia no cobra.

```
0 recuerdos -> purga a 30 días activos
1 recuerdo -> purga a 60 días activos
2 o más espaciados en 90 -> circuito largo: work 105 días activos,
social 5 años y después permastore
rama con hojas -> intacta
rama sin hojas -> cae (guarda anti-carrera de un ciclo)
```

Por qué así y no un umbral del motor bayesiano: `deletion_threshold` es un
default único de clase y el motor suma +0,5 α por recuperación, de modo que el
mismo θ daría 105 días para un engrama sin usar y ~30.700 para uno promovido
(ver RFC §6.1). La forma —recencia × frecuencia, con ventana reciente— viene de
Anderson & Schooler (1991); el espaciado, de Bjork & Bjork (1992); el permastore
de los 5 años, de Bahrick (1984). Los números son nuestros.

Modos (`SW_FORGETTING_LADDER_MODE`): `off` | `dry_run` (informe, cero escrituras)
| `enforce`. El defecto seguro es `off`.
"""

from __future__ import annotations

import json
import logging
import time
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

logger = logging.getLogger(__name__)

# Colecciones con circuito largo y su unidad. El resto no entra: directivas,
# interacción, alma y señales tienen su propio gobierno.
WORK_LIKE = frozenset({"work_memories", "skill_memories"})
SOCIAL_LIKE = frozenset({"social_memories", "story_memories"})
LADDER_COLLECTIONS = WORK_LIKE | SOCIAL_LIKE

HUB_PHASE = "synthesis_hub"


@dataclass(frozen=True)
class LadderParams:
	"""Los números de la escalera. Todos en días ACTIVOS salvo `social_years`."""

	sink_days_0_recalls: int = 30
	sink_days_1_recall: int = 60
	work_circuit_days: int = 105
	social_years: float = 5.0
	promotion_window_days: int = 90
	hub_reap_min_age_hours: float = 12.0


DEFAULTS = LadderParams()

# Reloj de días activos


def _state_path():
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "olvido_active_days.json"


def _read_state() -> Optional[Dict[str, Any]]:
	import json

	try:
		with open(_state_path(), encoding="utf-8") as fh:
			data = json.load(fh)
		return data if isinstance(data, dict) else None
	except FileNotFoundError:
		return None
	except Exception as exc:
		# Un fichero corrupto NO puede reiniciar el reloj en silencio (R3-C-09).
		logger.error(f"[OLVIDO] Estado del reloj ilegible ({_state_path()}): {exc}")
		return None


def _write_state(data: Dict[str, Any]) -> bool:
	"""Escritura atómica: un corte a medias no puede mover el reloj."""
	import json
	import os
	import tempfile

	path = _state_path()
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".olvido-", suffix=".json")
		with os.fdopen(fd, "w", encoding="utf-8") as fh:
			json.dump(data, fh)
		os.replace(tmp, path)
		return True
	except Exception as exc:
		logger.error(f"[OLVIDO] No se pudo escribir el estado del reloj: {exc}")
		return False


def _mirror_days(after_date: Optional[str] = None) -> Optional[List[float]]:
	"""Días con actividad según `session_mirror` (solo los posteriores a `after_date`)."""
	import sqlite3

	from red_pill.core.paths import get_session_db

	sql = "SELECT DISTINCT date(ts,'unixepoch','localtime') FROM session_mirror"
	args: tuple = ()
	if after_date:
		sql += " WHERE date(ts,'unixepoch','localtime') > ?"
		args = (after_date,)
	try:
		with sqlite3.connect(str(get_session_db())) as conn:
			rows = conn.execute(sql + " ORDER BY 1", args).fetchall()
	except Exception as exc:
		logger.warning(f"[OLVIDO] Reloj de días activos ilegible: {exc}")
		return None
	out: List[float] = []
	for (day,) in rows:
		try:
			out.append(time.mktime(time.strptime(str(day), "%Y-%m-%d")))
		except Exception:
			continue
	return out


def active_day_clock(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
	"""Reloj monótono de días activos: `{"epoch": N, "days": [...], "started_epoch": M}`.

	El contador **solo avanza** y lo lleva el propio olvido, no la tabla: un
	índice posicional sobre `session_mirror` se rompía con la retención (30 días)
	o con un backfill, cobrando olvido que nunca ocurrió (R3-C-04). Aquí los días
	nuevos se suman al epoch y los viejos que reaparezcan se ignoran.

	Devuelve `None` si no se puede leer o escribir: sin reloj no se decide nada
	(fail-closed), en vez de inventarse un `0` que marcaría todo como viejísimo.
	"""
	now = time.time() if now is None else now
	state = _read_state()
	if state is None:
		# Arranque: semilla con el histórico disponible (una vez).
		seed = _mirror_days()
		if seed is None:
			return None
		days = sorted(seed)[-500:]
		state = {
			"epoch": len(days),
			"days": days,
			"last_date": time.strftime("%Y-%m-%d", time.localtime(days[-1])) if days else "",
			"started_epoch": len(days),
		}
		if not _write_state(state):
			return None
		return state

	new = _mirror_days(state.get("last_date") or None)
	if new is None:
		return None
	days = sorted(list(state.get("days") or []) + list(new))[-500:]
	if new:
		state["epoch"] = int(state.get("epoch") or 0) + len(new)
		state["last_date"] = time.strftime("%Y-%m-%d", time.localtime(max(new)))
		state["days"] = days
		state.setdefault("started_epoch", state["epoch"])
		if not _write_state(state):
			return None
	state["days"] = days
	return state


def active_days_between(days: List[float], since: float, now: Optional[float] = None) -> int:
	"""Días activos estrictamente posteriores a `since` (y no posteriores a `now`)."""
	if not days:
		return 0
	now = time.time() if now is None else now
	lo = bisect_left(days, since)
	hi = bisect_left(days, now)
	return max(0, hi - lo)


def _window_start(days: List[float], window: int, now: float) -> float:
	"""Instante de la ventana de `window` días activos hacia atrás."""
	if not days:
		return now
	hi = bisect_left(days, now)
	idx = max(0, hi - window)
	return days[idx] if idx < len(days) else now


# Clasificación


def _ts(value: Any) -> Optional[float]:
	"""Timestamp tolerante: float, int o ISO-8601. None si no se puede leer.

	Un payload importado con fecha ISO tumbaba la pasada entera (y con ella el
	informe) por un `float()` sobre un string. Ahora se degrada a `None`, que
	significa «no lo sé» y no decide nada.
	"""
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, str) and value.strip():
		try:
			return float(value)
		except (TypeError, ValueError):
			pass
		try:
			from datetime import datetime

			return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
		except Exception:
			return None
	return None


def _promotion_stamps(payload: Dict[str, Any], days: List[float], now: float, params: LadderParams) -> int:
	"""Recuperaciones válidas para la puerta: 2 en días distintos dentro de 90 días activos."""
	stamps = [t for t in (_ts(s) for s in (payload.get("recall_stamps") or [])) if t is not None]
	if not stamps:
		return 0
	start = _window_start(days, params.promotion_window_days, now)
	recent = [s for s in stamps if s >= start]
	distinct = {time.strftime("%Y-%m-%d", time.localtime(s)) for s in recent}
	return len(distinct)


def _since_days(payload: Dict[str, Any], clock: Dict[str, Any], now: float) -> int:
	"""Días activos sin usar (la magnitud que decide). Extraído para ordenar."""
	epoch = int(clock.get("epoch") or 0)
	days = list(clock.get("days") or [])
	idx = payload.get("active_days_at_recall")
	if isinstance(idx, int) and 0 <= idx <= epoch:
		return epoch - idx
	last = _ts(payload.get("last_recalled_at")) or _ts(payload.get("created_at")) or now
	started = clock.get("started_epoch")
	grace = max(0, epoch - int(started if started is not None else epoch))
	real_since = active_days_between(days, last, now) if days else grace
	return min(real_since, grace)


def classify(
	payload: Dict[str, Any],
	collection: str,
	clock: Dict[str, Any],
	now: Optional[float] = None,
	params: LadderParams = DEFAULTS,
) -> str:
	"""Devuelve el destino de un engrama: `keep`, `delete`, `freeze` o `promote`.

	`clock` es el estado de `active_day_clock()`: `epoch` (días activos
	acumulados, monótono) y `days` (sus instantes, para las ventanas).
	"""
	if collection not in LADDER_COLLECTIONS:
		return "keep"
	now = time.time() if now is None else now
	if payload.get("immune") or payload.get("permastore"):
		return "keep"
	if payload.get("lazarus_phase") == HUB_PHASE or payload.get("node_type") == HUB_PHASE:
		return "keep"  # las ramas las juzga el reaper, no la escalera

	last = _ts(payload.get("last_recalled_at")) or _ts(payload.get("created_at"))
	if last is None:
		return "keep"  # sin fecha legible no se olvida: fail-closed

	days = list(clock.get("days") or [])
	since = _since_days(payload, clock, now)
	raw_stamps = [s for s in (_ts(s) for s in (payload.get("recall_stamps") or [])) if s is not None]
	stamps = _promotion_stamps(payload, days, now, params)
	# Transición de legacy (§8.2). Ojo: NO puede depender de que los stamps estén
	# ausentes, porque la propia migración los siembra con `[last_recalled_at]` y
	# apagaría la guarda (R3-A-02). Y exige que el último recuerdo esté dentro de
	# la ventana: un engrama parado hace tres años no entra al circuito largo.
	legacy_promoted = (
		int(payload.get("recall_count") or 0) >= 2 and len(raw_stamps) < 2 and last >= _window_start(days, params.promotion_window_days, now)
	)
	promoted = bool(payload.get("promoted_at")) or stamps >= 2 or legacy_promoted
	pending_promotion = promoted and not payload.get("promoted_at")

	if promoted:
		if collection in SOCIAL_LIKE:
			years = (now - last) / (365.25 * 86400.0)
			if years >= params.social_years:
				return "freeze"
			return "promote" if pending_promotion else "keep"
		if since >= params.work_circuit_days:
			return "delete"
		return "promote" if pending_promotion else "keep"

	if int(payload.get("recall_count") or 0) <= 0:
		return "delete" if since >= params.sink_days_0_recalls else "keep"
	return "delete" if since >= params.sink_days_1_recall else "keep"


def historical_since(payload: Dict[str, Any], clock: Dict[str, Any], now: Optional[float] = None) -> int:
	"""Días activos «reales» de un legacy, para el informe del dry_run.

	Solo tiene sentido para puntos SIN contador: para el resto, el planificado ya
	es el histórico y duplicar el cálculo no aportaba nada (R3-C-05).
	"""
	if isinstance(payload.get("active_days_at_recall"), int):
		return -1
	night = _ts(payload.get("last_recalled_at")) or _ts(payload.get("created_at"))
	if night is None:
		return -1
	return active_days_between(list(clock.get("days") or []), night, time.time() if now is None else now)


@dataclass
class LadderReport:
	"""Dos cuentas separadas: lo PLANIFICADO y lo EJECUTADO (R3-C-06)."""

	collection: str
	planned_delete: List[str] = field(default_factory=list)
	frozen: List[str] = field(default_factory=list)
	promoted: List[str] = field(default_factory=list)
	kept: int = 0
	errors: int = 0
	historical_delete: int = 0
	applied_freeze: int = 0
	applied_promote: int = 0
	write_errors: int = 0

	def as_dict(self) -> Dict[str, Any]:
		return {
			"collection": self.collection,
			"planned_delete": len(self.planned_delete),
			"frozen": len(self.frozen),
			"promoted": len(self.promoted),
			"kept": self.kept,
			"errors": self.errors,
			"historical_delete": self.historical_delete,
			"applied_freeze": self.applied_freeze,
			"applied_promote": self.applied_promote,
			"write_errors": self.write_errors,
		}


def _scroll_all(client, collection: str) -> List[Any]:
	out: List[Any] = []
	offset = None
	while True:
		batch, offset = client.scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
		out.extend(batch)
		if offset is None:
			return out


def run_ladder(
	memory_manager,
	mode: str = "dry_run",
	params: LadderParams = DEFAULTS,
	report_path: Optional[str] = None,
) -> Dict[str, Any]:
	"""Recorre las colecciones de la escalera y aplica (o informa) la decisión."""
	mode = (mode or "off").strip().lower()
	if mode not in ("off", "dry_run", "enforce"):
		logger.warning(f"[OLVIDO] Modo desconocido {mode!r}: se trata como 'off'.")
		return {"mode": "off", "collections": {}}
	if mode == "off":
		return {"mode": "off", "collections": {}}

	client = memory_manager.client
	now = time.time()
	clock = active_day_clock(now)
	if not clock or not clock.get("epoch"):
		logger.warning("[OLVIDO] Sin reloj fiable de días activos: no se decide nada en esta pasada (fail-closed).")
		return {"mode": mode, "collections": {}}
	reports: Dict[str, Any] = {}
	for collection in sorted(LADDER_COLLECTIONS):
		if not client.collection_exists(collection):
			continue
		report = LadderReport(collection=collection)
		to_delete: List[Any] = []
		to_freeze: List[Any] = []
		to_promote: List[Any] = []
		for point in _scroll_all(client, collection):
			try:
				decision = classify(point.payload or {}, collection, clock, now, params)
			except Exception as exc:  # un payload raro no puede tumbar la pasada
				report.errors += 1
				logger.warning(f"[OLVIDO] {collection}: no se pudo clasificar {point.id}: {exc}")
				continue
			if mode == "dry_run":
				try:
					h = historical_since(point.payload or {}, clock, now)
					if h >= 0 and h >= params.sink_days_0_recalls and decision != "delete":
						report.historical_delete += 1
				except Exception:
					pass
			if decision != "keep":
				logger.debug(
					json.dumps(
						{
							"event": "ladder_decision",
							"collection": collection,
							"id": str(point.id),
							"decision": decision,
							"mode": mode,
							"recall_count": int((point.payload or {}).get("recall_count") or 0),
						}
					)
				)
			if decision == "delete":
				report.planned_delete.append(str(point.id))
				to_delete.append((_since_days(point.payload or {}, clock, now), str(point.id)))
			elif decision == "freeze":
				report.frozen.append(str(point.id))
				to_freeze.append(point.id)
			elif decision == "promote":
				report.promoted.append(str(point.id))
				to_promote.append(point.id)
			else:
				report.kept += 1
			del decision

		# Rampa (R4-02): se purga primero lo MÁS parado, y como máximo N por
		# pasada. Una escalera se sube; no se salta 92 % del corpus en una noche.
		cap = int(getattr(cfg, "SW_FORGETTING_MAX_PURGES_PER_CYCLE", 0) or 0)
		to_delete.sort(key=lambda item: -item[0])
		deferred = 0
		if cap > 0 and len(to_delete) > cap:
			deferred = len(to_delete) - cap
			to_delete = to_delete[:cap]
			logger.info(f"[OLVIDO] {collection}: rampa activa, {deferred} purgas diferidas a próximas pasadas.")
		to_delete_ids = [pid for _, pid in to_delete]

		report_dict = report.as_dict()
		report_dict["deferred"] = deferred
		if mode == "enforce":
			from qdrant_client import models as qm

			if to_delete_ids:
				try:
					client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=to_delete_ids))
					report_dict["applied_delete"] = len(to_delete_ids)
					logger.info(f"[OLVIDO] {collection}: {len(to_delete_ids)} engramas purgados (escalera).")
				except Exception as exc:
					report_dict["write_errors"] = report_dict.get("write_errors", 0) + 1
					logger.error(f"[OLVIDO] Fallo purgando en {collection}: {exc}")
			if to_freeze:
				try:
					client.set_payload(
						collection_name=collection,
						payload={"permastore": True, "frozen_at": now, "updated_at": now},
						points=to_freeze,
					)
					report_dict["applied_freeze"] = len(to_freeze)
					logger.info(f"[OLVIDO] {collection}: {len(to_freeze)} engramas a permastore (congelados).")
				except Exception as exc:
					report_dict["write_errors"] = report_dict.get("write_errors", 0) + 1
					logger.error(f"[OLVIDO] Fallo congelando en {collection}: {exc}")
			if to_promote:
				try:
					client.set_payload(
						collection_name=collection,
						payload={"promoted_at": now, "updated_at": now},
						points=to_promote,
					)
					report_dict["applied_promote"] = len(to_promote)
					logger.info(f"[OLVIDO] {collection}: {len(to_promote)} engramas promovidos al circuito largo.")
				except Exception as exc:
					report_dict["write_errors"] = report_dict.get("write_errors", 0) + 1
					logger.error(f"[OLVIDO] Fallo promoviendo en {collection}: {exc}")

		reports[collection] = report_dict

	if mode == "enforce":
		applied = sum(int(c.get("applied_delete", 0) or 0) for c in reports.values())
		logger.info(
			f"[OLVIDO] Escalera enforce: {applied} purgas aplicadas de {sum(int(c.get('planned_delete', 0) or 0) for c in reports.values())} planificadas."
		)

	if report_path:
		try:
			with open(report_path, "w", encoding="utf-8") as fh:
				json.dump({"mode": mode, "at": now, "collections": reports}, fh, indent=1, ensure_ascii=False)
		except Exception as exc:
			logger.warning(f"[OLVIDO] No se pudo escribir el informe {report_path}: {exc}")
	return {"mode": mode, "collections": reports}


# Reaper de ramas (D-02): una rama sin hojas cae esa noche


def reap_leafless_branches(memory_manager, mode: str = "dry_run", params: LadderParams = DEFAULTS) -> Dict[str, Any]:
	"""Borra las ramas sin hojas, con guarda anti-carrera y sin tocar lo auto-contenido.

	Una rama recién escrita puede no tener sus miembros marcados todavía
	(`_mark_members` va DESPUÉS del upsert), de ahí la guarda de un ciclo. Y un
	hub creado por `promote_orphan_chunks` **es** su propio contenido: no es una
	rama de nadie y no se toca.
	"""
	from red_pill.metabolism.maintenance import _count_hub_members

	mode = (mode or "off").strip().lower()
	if mode not in ("dry_run", "enforce"):
		return {"mode": mode, "reaped": 0, "candidates": 0}

	from qdrant_client import models as qm

	client = memory_manager.client
	now = time.time()
	min_age = params.hub_reap_min_age_hours * 3600.0
	total_candidates = total_reaped = 0

	for collection in sorted(LADDER_COLLECTIONS):
		if not client.collection_exists(collection):
			continue
		hubs = client.scroll(
			collection_name=collection,
			scroll_filter=qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value=HUB_PHASE))]),
			limit=5000,
			with_payload=True,
			with_vectors=False,
		)[0]
		if not hubs:
			continue
		members = _count_hub_members(client, collection)
		if members is None:
			logger.warning(f"[OLVIDO] Sin recuento de hojas en {collection}: el reaper no borra nada ahí (fail-closed).")
			continue

		reap: List[Any] = []
		for hub in hubs:
			payload = hub.payload or {}
			if payload.get("immune") or payload.get("promoted_from"):
				continue
			if members.get(str(hub.id), 0) > 0:
				continue
			last_write = float(payload.get("hub_members_checked_at") or payload.get("created_at") or 0)
			if now - last_write < min_age:
				continue
			reap.append(str(hub.id))
			logger.info(f"[OLVIDO] Rama sin hojas en {collection}: {hub.id} (0 miembros, última escritura hace {(now - last_write) / 3600:.1f} h).")

		total_candidates += len(reap)
		if mode == "enforce" and reap:
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=reap))
				total_reaped += len(reap)
				logger.info(f"[OLVIDO] Reaper: {len(reap)} ramas sin hojas retiradas de {collection}.")
			except Exception as exc:
				logger.error(f"[OLVIDO] Reaper: fallo al borrar ramas en {collection}: {exc}")

	return {"mode": mode, "reaped": total_reaped, "candidates": total_candidates}
