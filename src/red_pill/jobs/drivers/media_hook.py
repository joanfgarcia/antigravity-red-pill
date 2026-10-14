"""media_hook — validación del bloque `media:` de una receta (docs/CORE/MEDIA_MODELS.md).

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

import json
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

	# Handoff al harness por env (el harness corre en su venv, sin `red_pill`):
	# el job side adapta; el harness consume los params ya adaptados.
	env = payload.setdefault("env", {})
	if result.get("model"):
		env["RP_MEDIA_MODEL"] = str(result["model"])
	adapted = result.get("adapted") or {}
	if "width" in adapted:
		env["RP_MEDIA_WIDTH"] = str(adapted["width"])
	if "height" in adapted:
		env["RP_MEDIA_HEIGHT"] = str(adapted["height"])
	if warnings:
		env["RP_MEDIA_WARNINGS"] = json.dumps(warnings, ensure_ascii=False)
	return warnings


def media_env_for_element(payload: Dict[str, Any], element: Any) -> Dict[str, str]:
	"""Env `RP_MEDIA_*` adaptado **por elemento** (para element_job multi-modelo).

	Resuelve el modelo del elemento (o el de `media:`), adapta las dimensiones
	pedidas y devuelve las variables de entorno para el harness. Si la petición del
	elemento es imposible, devuelve `RP_MEDIA_ERROR` (el harness falla limpio; el
	elemento se marca saltado, no rompe el job).
	"""
	media = payload.get("media")
	if not media or not isinstance(media, dict):
		return {}

	model = element.get("model") if isinstance(element, dict) else None
	model = model or media.get("model")
	params = {k: media[k] for k in ("width", "height") if media.get(k) is not None}

	env: Dict[str, str] = {}
	try:
		profiles = media_router.get_media_profiles()
		resolved = profiles.resolve(task=media.get("task"), model=str(model) if model else None)
		adapted, warnings = profiles.adapt(resolved, params)
	except (MediaProfileError, MediaCapabilityError) as e:
		env["RP_MEDIA_ERROR"] = str(e)
		return env

	env["RP_MEDIA_MODEL"] = resolved
	if "width" in adapted:
		env["RP_MEDIA_WIDTH"] = str(adapted["width"])
	if "height" in adapted:
		env["RP_MEDIA_HEIGHT"] = str(adapted["height"])
	if warnings:
		env["RP_MEDIA_WARNINGS"] = json.dumps(warnings, ensure_ascii=False)
	return env
