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


def active_days(now: Optional[float] = None) -> List[float]:
	"""Instantes (medianoche local) de los días con actividad, ascendentes.

	Fuente: `session_mirror.ts` de `queue/session.db`. El registro
	`chronicle_daily_registry.json` está retirado desde 2026-09-11 y no sirve.
	Si la base no está disponible se devuelve lista vacía: con cero días activos
	ningún fusible avanza, que es el lado seguro (nadie muere por un fallo de
	lectura).
	"""
	import sqlite3

	from red_pill.core.paths import get_session_db

	try:
		with sqlite3.connect(str(get_session_db())) as conn:
			rows = conn.execute("SELECT DISTINCT date(ts,'unixepoch','localtime') FROM session_mirror ORDER BY 1").fetchall()
	except Exception as exc:  # fail-safe: sin reloj, no hay olvido
		logger.warning(f"[OLVIDO] No se pudo leer el reloj de días activos: {exc}")
		return []
	days: List[float] = []
	for (d,) in rows:
		try:
			days.append(time.mktime(time.strptime(str(d), "%Y-%m-%d")))
		except Exception:
			continue
	return days


def active_days_between(days: List[float], since: float, now: Optional[float] = None) -> int:
	"""Días activos estrictamente posteriores a `since` (y no posteriores a `now`)."""
	if not days:
		return 0
	now = time.time() if now is None else now
	lo = bisect_left(days, since)
	hi = bisect_left(days, now)
	return max(0, hi - lo)


def ladder_started_at() -> float:
	"""Instante en que la escalera empezó a contar (D-16).

	Se guarda en un fichero de estado propio. La primera vez que se pregunta, se
	fija `now`: así ningún engrama legacy nace con 30 días activos de castigo por
	un histórico que ya venía truncado. Si no se puede escribir, se devuelve
	`now` en memoria (la pasada no purga, porque el reloj arranca hoy).
	"""
	import json

	from red_pill.core.paths import get_state_dir

	path = get_state_dir() / "olvido_ladder_started.json"
	try:
		with open(path, encoding="utf-8") as fh:
			return float(json.load(fh)["started_at"])
	except Exception:
		pass
	now = time.time()
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w", encoding="utf-8") as fh:
			json.dump({"started_at": now}, fh)
	except Exception as exc:
		logger.warning(f"[OLVIDO] No se pudo fijar el arranque de la escalera: {exc}")
	return now


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


def classify(
	payload: Dict[str, Any],
	collection: str,
	days: List[float],
	now: Optional[float] = None,
	params: LadderParams = DEFAULTS,
	ladder_start: Optional[float] = None,
) -> str:
	"""Devuelve el destino de un engrama: `keep`, `delete`, `freeze` o `promote`.

	Solo decide sobre las colecciones de la escalera: directivas, alma, señales
	e interacción tienen gobierno propio y salen siempre como `keep` (defensa en
	profundidad, aunque `run_ladder` no las recorra).
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

	# Días activos desde el último toque. Con contador (D-16) se usa el índice
	# guardado en la recuperación; sin contador (legacy) el reloj arranca en el
	# día de arranque de la escalera, para que la migración no purgue nada.
	idx = payload.get("active_days_at_recall")
	if isinstance(idx, int) and idx >= 0:
		since = max(0, len(days) - idx)
	else:
		since = active_days_between(days, max(last, ladder_start or last), now)

	# Puerta: 2 recuperaciones en días activos distintos dentro de 90 días.
	# Transición (§8.2): un legacy con `recall_count >= 2` y sin historia de
	# stamps entra al circuito largo sin exigir espaciado, porque el dato no
	# existe; a partir de ahí manda la regla nueva.
	stamps = _promotion_stamps(payload, days, now, params)
	legacy_promoted = int(payload.get("recall_count") or 0) >= 2 and not payload.get("recall_stamps")
	promoted = bool(payload.get("promoted_at")) or stamps >= 2 or legacy_promoted
	pending_promotion = promoted and not payload.get("promoted_at")

	if promoted:
		if collection in SOCIAL_LIKE:
			years = (now - last) / (365.25 * 86400.0)
			return "freeze" if years >= params.social_years else ("promote" if pending_promotion else "keep")
		if since >= params.work_circuit_days:
			return "delete"
		return "promote" if pending_promotion else "keep"

	if int(payload.get("recall_count") or 0) <= 0:
		return "delete" if since >= params.sink_days_0_recalls else "keep"
	return "delete" if since >= params.sink_days_1_recall else "keep"


# Ejecución


@dataclass
class LadderReport:
	"""Dos cuentas separadas: lo PLANIFICADO y lo EJECUTADO.

	Sumar lo planificado a la producción del sueño fue un hallazgo del
	adversarial: el parte decía `purga=N` aunque el borrado hubiera fallado o
	estuviera en `dry_run`.
	"""

	collection: str
	planned_delete: List[str] = field(default_factory=list)
	frozen: List[str] = field(default_factory=list)
	promoted: List[str] = field(default_factory=list)
	kept: int = 0
	errors: int = 0
	historical_delete: int = 0  # qué se llevaría el reloj histórico (solo dry_run)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"collection": self.collection,
			"planned_delete": len(self.planned_delete),
			"frozen": len(self.frozen),
			"promoted": len(self.promoted),
			"kept": self.kept,
			"errors": self.errors,
			"historical_delete": self.historical_delete,
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
	ladder_start: Optional[float] = None,
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
	days = active_days(now)
	if not days:
		logger.info("[OLVIDO] Sin reloj de días activos: no se decide nada en esta pasada.")
		return {"mode": mode, "collections": {}}

	# D-16: el reloj arranca el día de F3, no en el histórico. En `dry_run` se
	# informa ADEMÁS qué se llevaría el reloj histórico, para poder verlo sin
	# arriesgar nada (que es justo lo que pidió el Operador: «ver qué se va a
	# olvidar»).
	ladder_start = ladder_start if ladder_start is not None else ladder_started_at()
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
				decision = classify(point.payload or {}, collection, days, now, params, ladder_start=ladder_start)
			except Exception as exc:  # un payload raro no puede tumbar la pasada
				report.errors += 1
				logger.warning(f"[OLVIDO] {collection}: no se pudo clasificar {point.id}: {exc}")
				continue
			if mode == "dry_run":
				try:
					if classify(point.payload or {}, collection, days, now, params, ladder_start=0.0) == "delete":
						report.historical_delete += 1
				except Exception:
					pass
			if decision == "delete":
				report.planned_delete.append(str(point.id))
				to_delete.append(str(point.id))
			elif decision == "freeze":
				report.frozen.append(str(point.id))
				to_freeze.append(point.id)
			elif decision == "promote":
				report.promoted.append(str(point.id))
				to_promote.append(point.id)
			else:
				report.kept += 1
			del decision

		report_dict = report.as_dict()
		if mode == "enforce":
			from qdrant_client import models as qm

			if to_delete:
				try:
					client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=to_delete))
					report_dict["applied_delete"] = len(to_delete)
					logger.info(f"[OLVIDO] {collection}: {len(to_delete)} engramas purgados (escalera).")
				except Exception as exc:
					logger.error(f"[OLVIDO] Fallo purgando en {collection}: {exc}")
			if to_freeze:
				try:
					client.set_payload(
						collection_name=collection,
						payload={"permastore": True, "frozen_at": now, "updated_at": now},
						points=to_freeze,
					)
					logger.info(f"[OLVIDO] {collection}: {len(to_freeze)} engramas a permastore (congelados).")
				except Exception as exc:
					logger.error(f"[OLVIDO] Fallo congelando en {collection}: {exc}")
			if to_promote:
				try:
					client.set_payload(
						collection_name=collection,
						payload={"promoted_at": now, "updated_at": now},
						points=to_promote,
					)
					logger.info(f"[OLVIDO] {collection}: {len(to_promote)} engramas promovidos al circuito largo.")
				except Exception as exc:
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
