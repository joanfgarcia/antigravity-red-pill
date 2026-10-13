"""media_hook — validación del bloque `media:` de una receta (RFC-HARNESS-004 §8).

Enchufa el `media_router` en el **ensamblado** de la receta: `validate()` (submit)
y `preflight()` (pre-ejecución) de los drivers llaman aquí.

- **error** (petición imposible) → `MediaRecipeError` → aborta el encolado/step.
- **warning** (adaptación, p.ej. 1080→1088) → se registra en `payload['media_warnings']`.

El bloque `media:` (estructurado, no enterrado en `step_command`):
	media:
		task: typography   # o model: zimage_turbo
		width: 1920
		height: 1080
"""

from __future__ import annotations

from typing import Any, Dict, List

from red_pill.core import media_router
from red_pill.core.media_router import MediaCapabilityError, MediaProfileError


class MediaRecipeError(ValueError):
	"""El bloque `media:` de la receta es imposible de satisfacer en el ensamblado."""


def validate_media_payload(payload: Dict[str, Any]) -> List[str]:
	"""Valida/rutea `payload['media']` (si existe). Devuelve los warnings (y los persiste).

	Levanta `MediaRecipeError` si la petición es imposible (error limpio, no encolar).
	Escribe en el payload: `media_model`, `media_adapted`, `media_warnings`.
	"""
	media = payload.get("media")
	if not media:
		return []
	if not isinstance(media, dict):
		raise MediaRecipeError("payload.media debe ser un mapping")

	try:
		result = media_router.get_media_profiles().validate(media)
	except (MediaProfileError, MediaCapabilityError) as e:
		raise MediaRecipeError(f"elenco media no disponible: {e}")

	if result.get("status") == "error":
		raise MediaRecipeError("bloque media imposible: " + "; ".join(result.get("errors") or []))

	warnings = list(result.get("warnings") or [])
	payload["media_model"] = result.get("model")
	payload["media_adapted"] = result.get("adapted") or {}
	if warnings:
		payload["media_warnings"] = warnings
	return warnings
