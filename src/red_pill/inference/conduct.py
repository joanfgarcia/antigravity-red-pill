"""conduct — capa única de conducta por modelo (AD-049 corte 4).

Todo runner (battle python, battle HTTP, y los caminos de producción que se
sumen) ejecuta al modelo COMO PRODUCCIÓN: la conducta vive en el perfil ⊕ task
(`ResolvedModel`) y aquí se traduce a cada backend. Ningún runner reinventa
renderizado ni kwargs — así no vuelve a nacer la clase de caveat del
Granite-4.2-thinking en un harness nuevo.

Caminos:
- llama-cpp-python: `apply_python()` (handlers de thinking + chat_format
correcto) + `sampling_kwargs()`.
- HTTP (RuntimeServer / llama-server): `request_kwargs()` — samplers,
max_tokens y `chat_template_kwargs` (`enable_thinking` / `reasoning_effort`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SAMPLER_KEYS = ("temperature", "top_p", "top_k", "min_p")


def sampling_kwargs(resolved: Any, *, temperature: Optional[float] = None) -> Dict[str, Any]:
	"""Samplers efectivos: `resolved.temperature` ⊕ perfil.sampling.

	El override del llamador (p.ej. un Probe) gana. Sin override, el modelo
	usa SU receta (Granite 4.2 exige temperatura 1.0 — no la del harness).
	"""
	kwargs: Dict[str, Any] = {}
	if resolved is not None:
		t = getattr(resolved, "temperature", None)
		if t is not None:
			kwargs["temperature"] = float(t)
		for k, v in dict(getattr(resolved, "sampling", None) or {}).items():
			if k in _SAMPLER_KEYS and v is not None:
				kwargs[k] = v
	if temperature is not None:
		kwargs["temperature"] = float(temperature)
	return kwargs


def chat_template_kwargs(resolved: Any) -> Dict[str, Any]:
	"""Kwargs de template por conducta del modelo.

	`thinking: off` → `enable_thinking: false` (specie Qwen/Granite: el default
	del template es razonar y se apaga explícitamente). `reasoning_effort`
	declarado pasa tal cual (modelos que lo soportan; el resto lo ignora).
	"""
	ctk: Dict[str, Any] = {}
	if resolved is None:
		return ctk
	if getattr(resolved, "thinking", "off") == "off":
		ctk["enable_thinking"] = False
	effort = getattr(resolved, "reasoning_effort", None)
	if effort:
		ctk["reasoning_effort"] = effort
	return ctk


def request_kwargs(resolved: Any, *, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict[str, Any]:
	"""Body kwargs del camino HTTP (`RuntimeServer.chat`)."""
	kwargs = sampling_kwargs(resolved, temperature=temperature)
	mt = max_tokens or (getattr(resolved, "max_tokens", None) if resolved is not None else None)
	if mt:
		kwargs["max_tokens"] = int(mt)
	ctk = chat_template_kwargs(resolved)
	if ctk:
		kwargs["chat_template_kwargs"] = ctk
	return kwargs


def apply_python(llm: Any, resolved: Any, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Adapta un llama-cpp-python a la conducta del modelo; devuelve samplers.

	El registro de handlers es UNA vez por instancia (llama_cpp raisea en el
	re-registro global con el mismo nombre — se evita el ruido y el abort).
	"""
	from red_pill.inference import runtime as ir

	if not getattr(llm, "_rp_conduct_registered", False):
		ir.register_thinking_handlers(llm, resolved)
		llm._rp_conduct_registered = True
	ir.apply_chat_handler(llm, resolved, body or {})
	return sampling_kwargs(resolved)


def resolve_for_task(profile_name: str, task: Optional[str] = None) -> Optional[Any]:
	"""`ResolvedModel` del perfil con la conducta de la TAREA encima.

	Mismo criterio que el daemon para los modos custom/experimental: el perfil
	aporta modelo/hardware y la tarea aporta conducta (temperature, max_tokens,
	thinking, prompt_file). Existe para los runners que montan su propio `Llama`
	(battles, bake-offs) y deben medir COMO PRODUCCIÓN: sin esto un modelo con
	thinking declarado razona a pelo, se come el presupuesto de tokens y no llega
	a formatear la respuesta — se lee como suspenso del modelo cuando es del
	banco de pruebas.

	`task=None` → solo el perfil. Perfil no resoluble (id desconocido, gate de
	licencia) → None, y el runner sigue con su comportamiento por defecto.
	"""
	from red_pill.core import model_runtime as mr

	try:
		resolved = mr.resolve({"model": profile_name})
	except Exception as exc:  # perfil ausente / licencia / id inválido
		logger.warning(f"conduct: sin conducta para '{profile_name}' ({exc})")
		return None
	if not task:
		return resolved
	try:
		cfg = mr.resolve_task_conduct(task) or {}
	except Exception as exc:
		logger.warning(f"conduct: tarea '{task}' sin conducta ({exc})")
		return resolved
	if cfg.get("temperature") is not None:
		resolved.temperature = float(cfg["temperature"])
	if cfg.get("max_tokens"):
		resolved.max_tokens = int(cfg["max_tokens"])
	if cfg.get("thinking"):
		resolved.thinking = str(cfg["thinking"])
	if cfg.get("prompt_file"):
		resolved.prompt_file = str(cfg["prompt_file"])
	return resolved


def apply_task_profile(llm: Any, profile_name: str, task: Optional[str] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""`apply_python` resolviendo la conducta por NOMBRE de perfil ⊕ tarea.

	Azúcar para los runners que no pasan por el daemon (que resuelve por body).
	Sin perfil resoluble → {} y el runner se queda como estaba.
	"""
	resolved = resolve_for_task(profile_name, task)
	if resolved is None:
		return {}
	return apply_python(llm, resolved, body)
