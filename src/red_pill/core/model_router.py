"""Router de cascadas de modelos (RFC_TELEGRAM_RESILIENCE §2E/D20 — Fase 3).

Centraliza la resolución de qué cascade usar para un consumidor/rol/tarea,
reusando `ModelCatalog` (catálogo curado) + `CascadeBridge` + la política de
`NOTE_MODEL_POLICY_ROLES.md`.

Funciones:
	- `resolve_cascade(role, session_model=None)`: cascade del rol filtrada por
		gating de capacidad (D13/D15) y consciencia de quota (D20).
	- `mark_exhausted(target_label)`: recuerda que un target perdió la quota
		(AllModelsExhausted) para saltarlo en el siguiente intento.
	- `clear_quota_cache()`: resetea la consciencia de quota (p.ej. al arrancar).

El catálogo es la fuente de verdad; si no existe, se cae a la cascade del `.env`
(compatibilidad con la instalación actual). El worker sigue usando las env vars
como fallback cuando el catálogo está ausente.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Consciencia de quota (D20): labels de targets sin quota → saltados. In-memory
# (se resetea al reiniciar el worker); barato y suficiente para el hot path.
_quota_lock = threading.Lock()
_quota_exhausted: Dict[str, bool] = {}


class CascadeRouter:
	def __init__(self, catalog=None):
		from red_pill.core.model_catalog import ModelCatalog

		self._catalog = catalog or ModelCatalog()

	def resolve_cascade(
		self,
		role: str = "conversational",
		session_model: Optional[str] = None,
		allow_local: bool = False,
	) -> List[Dict[str, Any]]:
		"""Cascade de dicts BridgeTarget para el rol, filtrada por gating y quota.

		- Orden: priority del catálogo (roles.<role>).
		- Gating por capacidad (D13/D15): los modelos NO-CAPACES se filtran.
		- Consciencia de quota (D20): los targets sin quota se saltan.
		- `session_model` (D9): antepone el modelo de sesión sin duplicar.
		"""
		cascade = self._catalog.cascade_for(role=role, model_id=session_model, allow_local=allow_local)
		with _quota_lock:
			result = []
			for m in cascade:
				mid = m.get("id")
				if mid and not _quota_exhausted.get(str(mid)):
					result.append(m)
		return result

	def mark_exhausted(self, target_label: str) -> None:
		"""Registra que un target agotó la quota (AllModelsExhausted) → se salta."""
		with _quota_lock:
			_quota_exhausted[target_label] = True
		logger.info(f"[Router] Quota exhausted cached for '{target_label}' — saltando en el siguiente intento (D20)")

	def clear_quota_cache(self) -> None:
		"""Resetea la consciencia de quota (p.ej. arranque del worker)."""
		with _quota_lock:
			_quota_exhausted.clear()


def get_router() -> CascadeRouter:
	global _router_singleton
	if _router_singleton is None:
		_router_singleton = CascadeRouter()
	return _router_singleton


def clear_quota_cache() -> None:
	"""Resetea la consciencia de quota global (arranque del worker, tests)."""
	with _quota_lock:
		_quota_exhausted.clear()


_router_singleton: Optional[CascadeRouter] = None
