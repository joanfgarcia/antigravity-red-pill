"""media_hook — validación del bloque `media:` de una receta (docs/CORE/MEDIA_MODELS.md).

Enchufa el `media_router` en el **ensamblado** de la receta: `validate()` (submit)
y `preflight()` (pre-ejecución) de los drivers llaman aquí.

- **error** (petición imposible) → `MediaRecipeError` → aborta el encolado/step.
- **warning** (adaptación, p.ej. 1080→1088, o composición no soportada) → se registra en `payload['media_warnings']`.

El bloque `media:` (estructurado, no enterrado en `step_command`):
	media:
		task: typography   # o model: zimage_turbo
		width: 1920
		height: 1080
		composition:       # condicionamiento por imagen (opcional) — vocabulario en media_profiles
			reference_image: (PIL/path)   # se adapta/gatea; lo no soportado avisa (o falla en strict)

La **composición** y la **política** (`MEDIA_COMPOSITION_POLICY`) viajan al harness por **env** (`RP_MEDIA_*`),
**no** por `payload['env']`: el sanitizador de `script_job` (`base.sanitize_job_env`) borra `RP_*`, así que el env
media se inyecta aparte, **después** del sanitizado (`script.py::_build_env` lo aplica desde `payload['media_env']`).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from red_pill.core import media_router
from red_pill.core.media_router import MediaCapabilityError, MediaProfileError


class MediaRecipeError(ValueError):
	"""El bloque `media:` de la receta es imposible de satisfacer en el ensamblado."""


def _composition_policy() -> str:
	"""Política de composición (`compatible`|`strict`): de la config (que lee el `.env`); el entorno, de respaldo.

	La config recarga por mtime; leerla aquí (no de `os.environ`, que queda stale) mantiene router y harness en el
	mismo valor. Sin config disponible → `compatible` (fail-soft).
	"""
	try:
		from red_pill.config import get_config

		return str(get_config().MEDIA_COMPOSITION_POLICY or "compatible")
	except Exception:  # noqa: BLE001 — sin config, el default es fail-soft
		return os.getenv("MEDIA_COMPOSITION_POLICY", "compatible")


def _media_env(result: Dict[str, Any], policy: str) -> Dict[str, str]:
	"""Env `RP_MEDIA_*` a partir de un resultado de `validate()`/`adapt()` (modelo/adapted/warnings)."""
	env: Dict[str, str] = {"RP_MEDIA_COMPOSITION_POLICY": policy}
	if result.get("model"):
		env["RP_MEDIA_MODEL"] = str(result["model"])
	adapted = result.get("adapted") or {}
	if "width" in adapted:
		env["RP_MEDIA_WIDTH"] = str(adapted["width"])
	if "height" in adapted:
		env["RP_MEDIA_HEIGHT"] = str(adapted["height"])
	if adapted.get("composition"):
		env["RP_MEDIA_COMPOSITION"] = json.dumps(adapted["composition"], ensure_ascii=False)
	warnings = list(result.get("warnings") or [])
	if warnings:
		env["RP_MEDIA_WARNINGS"] = json.dumps(warnings, ensure_ascii=False)
	return env


def validate_media_payload(payload: Dict[str, Any]) -> List[str]:
	"""Valida/rutea `payload['media']` (si existe). Devuelve los warnings (y los persiste).

	Levanta `MediaRecipeError` si la petición es imposible (error limpio, no encolar).
	Escribe en el payload: `media_model`, `media_adapted`, `media_warnings` y `media_env` (env para el harness).
	"""
	media = payload.get("media")
	if not media:
		return []
	if not isinstance(media, dict):
		raise MediaRecipeError("payload.media debe ser un mapping")

	policy = _composition_policy()
	request = {k: media[k] for k in ("task", "model", "width", "height") if media.get(k) is not None}
	if media.get("composition") is not None:
		request["composition"] = media["composition"]

	try:
		result = media_router.get_media_profiles().validate(request, policy=policy)
	except (MediaProfileError, MediaCapabilityError) as e:
		raise MediaRecipeError(f"elenco media no disponible: {e}")

	if result.get("status") == "error":
		raise MediaRecipeError("bloque media imposible: " + "; ".join(result.get("errors") or []))

	warnings = list(result.get("warnings") or [])
	payload["media_model"] = result.get("model")
	payload["media_adapted"] = result.get("adapted") or {}
	if warnings:
		payload["media_warnings"] = warnings

	# Handoff al harness por env (el harness corre en su venv, sin `red_pill`). NO por `payload['env']`:
	# el sanitizador de script_job borra los `RP_*`, así que va en una clave propia que el driver aplica después.
	payload["media_env"] = _media_env(result, policy)
	return warnings


def media_env_for_element(payload: Dict[str, Any], element: Any) -> Dict[str, str]:
	"""Env `RP_MEDIA_*` adaptado **por elemento** (para element_job multi-modelo).

	Resuelve el modelo del elemento (o el de `media:`), adapta dimensiones y composición, y devuelve las variables
	de entorno para el harness. La **composición del elemento manda sobre la del job** (precedencia). Si la petición
	del elemento es imposible, devuelve `RP_MEDIA_ERROR` (el harness falla limpio; el elemento se marca saltado).
	"""
	media = payload.get("media")
	if not media or not isinstance(media, dict):
		return {}

	policy = _composition_policy()
	model = element.get("model") if isinstance(element, dict) else None
	model = model or media.get("model")
	params = {k: media[k] for k in ("width", "height") if media.get(k) is not None}
	comp = (element.get("composition") if isinstance(element, dict) else None) or media.get("composition")
	if comp is not None:
		params["composition"] = comp

	env: Dict[str, str] = {}
	try:
		profiles = media_router.get_media_profiles()
		resolved = profiles.resolve(task=media.get("task"), model=str(model) if model else None)
		adapted, warnings = profiles.adapt(resolved, params, policy=policy)
	except (MediaProfileError, MediaCapabilityError) as e:
		env["RP_MEDIA_ERROR"] = str(e)
		env["RP_MEDIA_COMPOSITION_POLICY"] = policy
		return env

	env.update(_media_env({"model": resolved, "adapted": adapted, "warnings": warnings}, policy))
	return env
