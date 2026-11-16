"""La escalera del olvido (RFC-OLV-001, F3) — **política, no parámetro**.

Una sola ruta decide olvidar, y decide en **días activos**: días en los que hubo
actividad real, nunca días de calendario. La ausencia no cobra.

```
0 recuerdos            -> purga a 30 días activos
1 recuerdo             -> purga a 60 días activos
>=2 espaciados (90 d)  -> circuito largo: work 105 días activos
                                          social 5 años -> PERMASTORE
rama con hojas         -> intacta
rama sin hojas         -> cae (guarda anti-carrera de un ciclo)
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

# ---------------------------------------------------------------------------
# Reloj de días activos
# ---------------------------------------------------------------------------


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


def _window_start(days: List[float], window: int, now: float) -> float:
	"""Instante de la ventana de `window` días activos hacia atrás."""
	if not days:
		return now
	hi = bisect_left(days, now)
	idx = max(0, hi - window)
	return days[idx] if idx < len(days) else now


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------


def _promotion_stamps(payload: Dict[str, Any], days: List[float], now: float, params: LadderParams) -> int:
	"""Recuperaciones válidas para la puerta: 2 en días distintos dentro de 90 días activos."""
	stamps = [float(s) for s in (payload.get("recall_stamps") or []) if isinstance(s, (int, float))]
	if not stamps:
		return 0
	start = _window_start(days, params.promotion_window_days, now)
	recent = [s for s in stamps if s >= start]
	distinct = {time.strftime("%Y-%m-%d", time.localtime(s)) for s in recent}
	return len(distinct)


def classify(payload: Dict[str, Any], collection: str, days: List[float], now: Optional[float] = None, params: LadderParams = DEFAULTS) -> str:
	"""Devuelve el destino de un engrama: `keep`, `delete` o `freeze`."""
	now = time.time() if now is None else now
	if payload.get("immune") or payload.get("permastore"):
		return "keep"
	if payload.get("lazarus_phase") == HUB_PHASE or payload.get("node_type") == HUB_PHASE:
		return "keep"  # las ramas las juzga el reaper, no la escalera

	last = float(payload.get("last_recalled_at") or payload.get("created_at") or now)
	since = active_days_between(days, last, now)

	# La promoción es una transición de estado, no un test rodante: una vez que
	# dos recuperaciones espaciadas la cruzan, el engrama entra al circuito
	# largo y se queda (`promoted_at`). Si se evaluara «en ventana» cada noche,
	# el permastore sería inalcanzable: exigiría 5 años de antigüedad y estar
	# recordado en los últimos 90 días activos a la vez.
	promoted = bool(payload.get("promoted_at")) or _promotion_stamps(payload, days, now, params) >= 2
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


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------


@dataclass
class LadderReport:
	collection: str
	deleted: List[str] = field(default_factory=list)
	frozen: List[str] = field(default_factory=list)
	promoted: List[str] = field(default_factory=list)
	kept: int = 0

	def as_dict(self) -> Dict[str, Any]:
		return {
			"collection": self.collection,
			"deleted": len(self.deleted),
			"frozen": len(self.frozen),
			"promoted": len(self.promoted),
			"kept": self.kept,
		}


def _scroll_all(client, collection: str) -> List[Any]:
	out: List[Any] = []
	offset = None
	while True:
		batch, offset = client.scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
		out.extend(batch)
		if offset is None:
			return out


def run_ladder(memory_manager, mode: str = "dry_run", params: LadderParams = DEFAULTS, report_path: Optional[str] = None) -> Dict[str, Any]:
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

	reports: Dict[str, Any] = {}
	for collection in sorted(LADDER_COLLECTIONS):
		if not client.collection_exists(collection):
			continue
		report = LadderReport(collection=collection)
		to_delete: List[Any] = []
		to_freeze: List[Any] = []
		to_promote: List[Any] = []
		for point in _scroll_all(client, collection):
			decision = classify(point.payload or {}, collection, days, now, params)
			if decision == "delete":
				report.deleted.append(str(point.id))
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

		if mode == "enforce":
			from qdrant_client import models as qm

			if to_delete:
				try:
					client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=to_delete))
					logger.info(f"[OLVIDO] {collection}: {len(to_delete)} engramas purgados (escalera).")
				except Exception as exc:
					logger.error(f"[OLVIDO] Fallo purgando en {collection}: {exc}")
			if to_freeze:
				try:
					client.set_payload(collection_name=collection, payload={"permastore": True, "frozen_at": now}, points=to_freeze)
					logger.info(f"[OLVIDO] {collection}: {len(to_freeze)} engramas a permastore (congelados).")
				except Exception as exc:
					logger.error(f"[OLVIDO] Fallo congelando en {collection}: {exc}")
			if to_promote:
				try:
					client.set_payload(collection_name=collection, payload={"promoted_at": now}, points=to_promote)
					logger.info(f"[OLVIDO] {collection}: {len(to_promote)} engramas promovidos al circuito largo.")
				except Exception as exc:
					logger.error(f"[OLVIDO] Fallo promoviendo en {collection}: {exc}")

		reports[collection] = report.as_dict()

	if report_path:
		try:
			with open(report_path, "w", encoding="utf-8") as fh:
				json.dump({"mode": mode, "at": now, "collections": reports}, fh, indent=1, ensure_ascii=False)
		except Exception as exc:
			logger.warning(f"[OLVIDO] No se pudo escribir el informe {report_path}: {exc}")
	return {"mode": mode, "collections": reports}


# ---------------------------------------------------------------------------
# Reaper de ramas (D-02): una rama sin hojas cae esa noche
# ---------------------------------------------------------------------------


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

	client = memory_manager.client
	collection = "work_memories"
	if not client.collection_exists(collection):
		return {"mode": mode, "reaped": 0, "candidates": 0}

	from qdrant_client import models as qm

	hubs = client.scroll(
		collection_name=collection,
		scroll_filter=qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value=HUB_PHASE))]),
		limit=5000,
		with_payload=True,
		with_vectors=False,
	)[0]
	members = _count_hub_members(client, collection)
	if members is None:
		logger.warning("[OLVIDO] Sin recuento de hojas: el reaper no borra nada en esta pasada (fail-closed).")
		return {"mode": mode, "reaped": 0, "candidates": 0}

	now = time.time()
	min_age = params.hub_reap_min_age_hours * 3600.0
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
		logger.info(f"[OLVIDO] Rama sin hojas: {hub.id} (miembros=0, última escritura hace {(now - last_write) / 3600:.1f} h).")

	if mode == "enforce" and reap:
		try:
			client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=reap))
			logger.info(f"[OLVIDO] Reaper: {len(reap)} ramas sin hojas retiradas.")
		except Exception as exc:
			logger.error(f"[OLVIDO] Reaper: fallo al borrar ramas: {exc}")
			return {"mode": mode, "reaped": 0, "candidates": len(reap)}
	return {"mode": mode, "reaped": len(reap) if mode == "enforce" else 0, "candidates": len(reap)}
