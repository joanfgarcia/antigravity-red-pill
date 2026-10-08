"""conduct — capa única de conducta por modelo (RFC-HARNESS-003 corte 4).

Todo runner (battle python, battle HTTP, y los caminos de producción que se
sumen) ejecuta al modelo COMO PRODUCCIÓN: la conducta vive en el perfil ⊕ task
(`ResolvedModel`) y aquí se traduce a cada backend. Ningún runner reinventa
renderizado ni kwargs — así no vuelve a nacer la clase de caveat del
Granite-4.2-thinking en un harness nuevo.

- Camino llama-cpp-python: `apply_python()` (handlers de thinking +
  chat_format correcto) + `sampling_kwargs()`.
- Camino HTTP (RuntimeServer / llama-server): `request_kwargs()` — samplers,
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
