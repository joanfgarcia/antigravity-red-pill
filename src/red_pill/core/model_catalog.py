"""Catálogo curado de modelos (RFC_TELEGRAM_RESILIENCE §2A/D6-D9/D20).

Fuente de verdad de qué modelos existen y se pueden usar. Sustituye a la oferta
completa de `opencode models` (81 modelos) y a las 3 env vars de cascade como
fuente de modelos. Sigue el patrón de `model_profiles.yaml`.

Estructura (`model_catalog.yaml`):
	catalog:
		providers:
			<backend>:
				models:
					- id, backend, tier, priority, roles, capabilities, not_capable_for, timeout
	roles:
		<role>: [model_id, ...]   # cascade ordenada por rol

El CLI `red-pill telegram models` lista el catálogo; `red-pill roles` lista los
roles y su cascade. Sin agente — solo lectura.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from red_pill.core.paths import get_model_catalog_path

logger = logging.getLogger(__name__)

_DEFAULT_TIERS = {"subscription", "free", "local"}
_DEFAULT_ROLES = {"scout", "planning", "coder", "conversational"}


class ModelCatalogError(Exception):
	"""Catálogo ausente, malformado o sin modelos configurados."""


def _load_yaml(path: Path) -> Dict[str, Any]:
	try:
		with open(path, "r", encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
	except FileNotFoundError:
		raise ModelCatalogError(f"model_catalog.yaml no encontrado en {path} (copia examples/model_catalog.yaml.example).")
	except yaml.YAMLError as e:
		raise ModelCatalogError(f"model_catalog.yaml malformado en {path}: {e}")
	return data


def _flatten(data: Dict[str, Any]) -> List[Dict[str, Any]]:
	"""Aplana `catalog.providers.<backend>.models[]` a una lista con `backend` por modelo."""
	out: List[Dict[str, Any]] = []
	for backend, provider in (data.get("catalog", {}).get("providers", {}) or {}).items():
		for model in provider.get("models", []) or []:
			entry = dict(model)
			entry.setdefault("backend", backend)
			out.append(entry)
	return out


class ModelCatalog:
	"""Acceso de solo lectura al catálogo curado.

	Carga el YAML una vez por instancia. Las operaciones devuelven copias para
	no mutar el estado interno.
	"""

	def __init__(self, path: Optional[Path] = None):
		self.path = path or get_model_catalog_path()
		self._data: Dict[str, Any] = {}
		self._models: List[Dict[str, Any]] = []
		self._loaded = False

	def _ensure_loaded(self) -> None:
		if self._loaded:
			return
		self._data = _load_yaml(self.path)
		self._models = _flatten(self._data)
		self._loaded = True

	def models(self, backend: Optional[str] = None, tier: Optional[str] = None) -> List[Dict[str, Any]]:
		"""Modelos del catálogo, ordenados por `priority` (lower first)."""
		self._ensure_loaded()
		models = self._models
		if backend:
			models = [m for m in models if m.get("backend") == backend]
		if tier:
			models = [m for m in models if m.get("tier") == tier]
		return sorted(models, key=lambda m: m.get("priority", 999))

	def get(self, model_id: str) -> Optional[Dict[str, Any]]:
		"""Busca un modelo por id. None si no está curado (D7: se rechaza)."""
		self._ensure_loaded()
		for m in self._models:
			if m.get("id") == model_id:
				return dict(m)
		return None

	def backend_for(self, model_id: str) -> Optional[str]:
		"""Backend del modelo, DEL CATÁLOGO (D8 — no se infiere por prefijo)."""
		entry = self.get(model_id)
		return entry.get("backend") if entry else None

	def cascade_for(
		self,
		role: Optional[str] = None,
		model_id: Optional[str] = None,
		allow_local: bool = False,
	) -> List[Dict[str, Any]]:
		"""Cascade de BridgeTarget (dicts) para un rol o modelo de sesión.

		- `model_id` (sesión, D9): antepone el modelo de sesión a la cascade del
			rol, sin duplicar si ya coincide con algún target.
		- `role`: cascade ordenada del catálogo (roles.<role>).
		- Gating D13/D15: los modelos NO-CAPACES para el rol se filtran; `local`
			solo si `allow_local=True` (guard D5).
		"""
		self._ensure_loaded()
		base: List[Dict[str, Any]] = []

		role_cascade = (self._data.get("roles", {}) or {}).get(role or "conversational", [])
		for model_id_ in role_cascade:
			entry = self.get(model_id_)
			if not entry:
				continue
			base.append(entry)

		# Anteponer el modelo de sesión si no está ya en la cascade (D9).
		if model_id and not any(m.get("id") == model_id for m in base):
			entry = self.get(model_id)
			if entry:
				base.insert(0, entry)

		result: List[Dict[str, Any]] = []
		for entry in base:
			if role and role in (entry.get("not_capable_for") or []):
				continue  # D13 gating por capacidad
			if entry.get("backend") == "local" and not allow_local:
				continue  # D5 guard
			result.append(entry)
		return result

	def role_names(self) -> List[str]:
		"""Roles definidos en el catálogo."""
		self._ensure_loaded()
		return list((self._data.get("roles", {}) or {}).keys())


def get_catalog() -> ModelCatalog:
	"""Singleton conveniente del catálogo (barato: el YAML es pequeño)."""
	global _catalog_singleton
	if _catalog_singleton is None:
		_catalog_singleton = ModelCatalog()
	return _catalog_singleton


_catalog_singleton: Optional[ModelCatalog] = None
