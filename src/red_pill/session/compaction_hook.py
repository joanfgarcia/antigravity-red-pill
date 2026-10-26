"""Hook post-turno y safety net del compactor (B-02).

- `maybe_start_after_turn`: se llama tras importar un turno externo al espejo; chequeo barato + `maybe_start` durable, con `COMPACTOR_SCOPE`.
- `sweep_active_compactions`: red de seguridad de baja frecuencia; solo continuidades **activas** (leg activo y latido reciente), nunca históricas.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _config():
	try:
		import red_pill.config as cfg

		return cfg.get_config()
	except Exception:
		return None


def _enabled() -> bool:
	conf = _config()
	return bool(getattr(conf, "SESSION_COMPACTOR_ENABLED", False)) if conf is not None else False


def maybe_start_after_turn(
	mirror: Any,
	continuity_id: str,
	*,
	mission_id: str,
	originator: str,
	origin: Optional[str] = None,
	queue_manager: Any = None,
) -> Optional[str]:
	"""Chequeo barato tras un turno externo; encola el job si cruza el umbral."""
	if not _enabled():
		return None
	continuity = str(continuity_id or "").strip()
	if not continuity:
		return None
	try:
		from red_pill.session.compactor import Compactor

		compactor = Compactor(mirror, queue_manager=queue_manager)
		estimate = compactor.estimate_context_tokens(continuity)
		return compactor.maybe_start(
			continuity,
			mission_id=str(mission_id or ""),
			estimated_tokens=estimate,
			originator=str(originator or ""),
			origin=origin,
		)
	except Exception as e:  # noqa: BLE001 — el turno no debe caer por el compactor
		logger.warning("[compactor-hook] no se pudo encolar: %s", e)
		return None


def sweep_active_compactions(
	*,
	active_min: Optional[int] = None,
	limit: int = 500,
	db_path: Optional[str] = None,
	queue_manager: Any = None,
) -> Dict[str, Any]:
	"""Safety net: compacta continuidades activas (no históricas)."""
	conf = _config()
	if not bool(getattr(conf, "SESSION_COMPACTOR_ENABLED", False)):
		return {"enabled": False, "scanned": 0, "enqueued": 0}
	from red_pill.session.compactor import Compactor
	from red_pill.session.mirror import SessionMirror
	from red_pill.session.store import SessionRegistry

	window = int(active_min if active_min is not None else getattr(conf, "COMPACTOR_SWEEP_ACTIVE_MIN", 15))
	window = max(1, window)
	cutoff = time.time() - window * 60
	mirror = SessionMirror(db_path)
	compactor = Compactor(mirror, queue_manager=queue_manager)
	registry = SessionRegistry(db_path)
	seen: set[str] = set()
	scanned = 0
	enqueued = 0
	for row in registry.list_sessions(max(1, min(int(limit), 5000))):
		if str(row.get("ttl_state") or "") != "active":
			continue
		continuity = str(row.get("continuity_id") or "").strip()
		if not continuity or continuity in seen:
			continue
		# El registro solo se toca al crear el leg; un turno fresco del espejo
		# debe mantener viva la continuidad para el safety net.
		last_activity = max(float(row.get("updated_at") or 0.0), mirror.last_completed_ts(continuity))
		if last_activity < cutoff:
			continue
		seen.add(continuity)
		scanned += 1
		estimate = compactor.estimate_context_tokens(continuity)
		job = compactor.maybe_start(
			continuity,
			mission_id=str(row.get("mission_id") or ""),
			estimated_tokens=estimate,
			originator=str(row.get("originator") or ""),
		)
		if job:
			enqueued += 1
	return {"enabled": True, "active_min": window, "scanned": scanned, "enqueued": enqueued}
