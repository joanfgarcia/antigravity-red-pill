"""media_router — router por tarea y adaptadores de modelo para media (RFC-HARNESS-004).

Compartido por imagen y audio (misma estructura: pipeline + sampler + quant + VRAM).
Espeja el contrato de `model_catalog.py` (roles/cascade/`not_capable_for`) para media
y añade `constraints`/`adapters`: cada modelo declara sus peculiaridades (divisor de
resolución, topes de píxeles/VRAM) y el motor las aplica **por nombre**, sin ramas
por modelo (añadir un modelo = añadir metadata, no código).

Semántica (RFC-HARNESS-004 §7.3): lo adaptable → **warning**; lo imposible → **error
limpio** (`MediaCapabilityError`). Nunca fallback silencioso.

`resolve(task, model)` resuelve **modelos** (imagen/audio). La música simbólica es un
**tool-chain** (no un modelo): su resolución es a **receta**, fuera de este motor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from red_pill.core.paths import get_media_profiles_path

logger = logging.getLogger(__name__)


class MediaProfileError(Exception):
	"""Elenco media ausente, malformado, sin modelos o con un adapter desconocido."""


class MediaCapabilityError(RuntimeError):
	"""Petición imposible de satisfacer (no resoluble ni adaptable) — fallo limpio."""


def _load_yaml(path: Path) -> Dict[str, Any]:
	try:
		with open(path, "r", encoding="utf-8") as f:
			data: Any = yaml.safe_load(f) or {}
	except FileNotFoundError:
		raise MediaProfileError(f"media_profiles.yaml no encontrado en {path} (copia examples/media_profiles.yaml.example).")
	except yaml.YAMLError as e:
		raise MediaProfileError(f"media_profiles.yaml malformado en {path}: {e}")
	if not isinstance(data, dict):
		raise MediaProfileError(f"media_profiles.yaml raíz inválida en {path} (se esperaba un mapping).")
	return data


# Un adapter recibe (params, profile) y devuelve (params_mutado, warnings) o levanta
# MediaCapabilityError si no puede satisfacer la petición.

Adapter = Callable[[Dict[str, Any], Dict[str, Any]], Tuple[Dict[str, Any], List[str]]]


def _adapter_snap_dims(params: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
	"""Ajusta width/height al múltiplo `constraints.dim_multiple` (hacia arriba)."""
	constraints = profile.get("constraints") or {}
	mult = int(constraints.get("dim_multiple") or 1)
	if mult <= 1:
		return params, []
	mid = profile.get("id") or "?"
	warnings: List[str] = []
	for axis in ("width", "height"):
		value = params.get(axis)
		if value is None:
			continue
		value = int(value)
		snapped = max(mult, round(value / mult) * mult)
		if snapped != value:
			warnings.append(f"{axis} {value}→{snapped} (÷{mult} de {mid})")
		params[axis] = snapped
	return params, warnings


def _adapter_reject_oversize(params: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
	"""Rechaza (error limpio) resoluciones por encima de `max_pixels` o footprints sobre `max_vram_mb`."""
	constraints = profile.get("constraints") or {}
	mid = profile.get("id") or "?"
	max_pixels = constraints.get("max_pixels")
	width, height = params.get("width"), params.get("height")
	if max_pixels and width and height and int(width) * int(height) > int(max_pixels):
		raise MediaCapabilityError(f"{mid}: {width}x{height} excede max_pixels={max_pixels}")
	max_vram = constraints.get("max_vram_mb")
	peak = (profile.get("vram_footprint") or {}).get("peak_mb")
	if max_vram and peak and float(peak) > float(max_vram):
		raise MediaCapabilityError(f"{mid}: pico ~{peak} MB excede max_vram_mb={max_vram}")
	return params, []


ADAPTERS: Dict[str, Adapter] = {
	"snap_dims": _adapter_snap_dims,
	"reject_oversize": _adapter_reject_oversize,
}


class MediaProfiles:
	"""Acceso de solo lectura al elenco media (`media_profiles.yaml`)."""

	def __init__(self, path: Optional[Path] = None):
		self.path = path or get_media_profiles_path()
		self._data: Dict[str, Any] = {}
		self._profiles: Dict[str, Dict[str, Any]] = {}
		self._loaded = False

	def _ensure_loaded(self) -> None:
		if self._loaded:
			return
		self._data = _load_yaml(self.path)
		raw = self._data.get("media_profiles") or {}
		if not isinstance(raw, dict):
			raise MediaProfileError(f"'media_profiles' debe ser un mapping en {self.path}")
		self._profiles = {mid: {**dict(profile), "id": mid} for mid, profile in raw.items() if isinstance(profile, dict)}
		self._loaded = True

	def profiles(self) -> Dict[str, Dict[str, Any]]:
		self._ensure_loaded()
		return {mid: dict(p) for mid, p in self._profiles.items()}

	def get(self, model_id: str) -> Optional[Dict[str, Any]]:
		self._ensure_loaded()
		profile = self._profiles.get(model_id)
		return dict(profile) if profile else None

	def role_names(self) -> List[str]:
		"""Tareas/intenciones declaradas en `media_roles`."""
		self._ensure_loaded()
		return list((self._data.get("media_roles") or {}).keys())

	def _task_cascade(self, task: str) -> List[str]:
		return [str(m) for m in (self._data.get("media_roles") or {}).get(task, [])]

	def resolve(self, task: Optional[str] = None, model: Optional[str] = None) -> str:
		"""Resuelve el modelo: `model` explícito > cascade de `task`; salta `not_capable_for`.

		Falla limpio (`MediaCapabilityError`) si no hay candidato.
		"""
		self._ensure_loaded()
		if not task and not model:
			raise MediaCapabilityError("resolve requiere 'task' o 'model'")

		ordered: List[str] = []
		if model:
			if model not in self._profiles:
				raise MediaCapabilityError(f"modelo '{model}' no está en el elenco")
			ordered.append(model)
		if task:
			cascade = self._task_cascade(task)
			if not cascade:
				raise MediaCapabilityError(f"task '{task}' sin modelos declarados en media_roles")
			for mid in cascade:
				if mid in self._profiles and mid not in ordered:
					ordered.append(mid)

		for mid in ordered:
			profile = self._profiles[mid]
			if task and task in (profile.get("not_capable_for") or []):
				continue
			return mid
		raise MediaCapabilityError(f"todos los modelos para task='{task}' están en not_capable_for")

	def adapt(self, model_id: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
		"""Aplica (por nombre) los adapters declarados por el modelo. Puede levantar MediaCapabilityError."""
		profile = self.get(model_id)
		if not profile:
			raise MediaCapabilityError(f"modelo '{model_id}' no está en el elenco")
		out = dict(params)
		warnings: List[str] = []
		for name in profile.get("adapters") or []:
			fn = ADAPTERS.get(str(name))
			if fn is None:
				raise MediaProfileError(f"adapter desconocido '{name}' en '{model_id}'")
			out, warns = fn(out, profile)
			warnings.extend(warns)
		return out, warnings

	def validate(self, request: Dict[str, Any]) -> Dict[str, Any]:
		"""Valida/rutea una petición de generación. Devuelve JSON estructurado.

		`{status: ok|adapted|error, model, adapted, warnings, errors}` — interpretable
		por el job_manager/dag en el ensamblado de la receta (RFC-HARNESS-004 §8).
		"""
		try:
			model = self.resolve(task=request.get("task"), model=request.get("model"))
		except MediaCapabilityError as e:
			return {"status": "error", "model": None, "adapted": {}, "warnings": [], "errors": [str(e)]}

		params = {k: request[k] for k in ("width", "height") if request.get(k) is not None}
		try:
			adapted, warnings = self.adapt(model, params)
		except MediaCapabilityError as e:
			return {"status": "error", "model": model, "adapted": {}, "warnings": [], "errors": [str(e)]}

		status = "adapted" if warnings else "ok"
		return {"status": status, "model": model, "adapted": adapted, "warnings": warnings, "errors": []}


_MEDIA_SINGLETON: Optional[MediaProfiles] = None


def get_media_profiles() -> MediaProfiles:
	"""Singleton conveniente del elenco media (barato: el YAML es pequeño)."""
	global _MEDIA_SINGLETON
	if _MEDIA_SINGLETON is None:
		_MEDIA_SINGLETON = MediaProfiles()
	return _MEDIA_SINGLETON
