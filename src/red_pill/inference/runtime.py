"""runtime.py — núcleo común de ejecución de inferencia (RFC-HARNESS-002 v3).

Dos fronts consumen esta librería (una sola verdad de renderizado):

- **daemon** (`~/.local/share/red-pill/daemon/run_dual_bind.py`): llama-cpp-python
  con handlers por modo thinking.
- **CLI** (harness de bake-off `scripts/bakeoff_granite_42.py`): llama-cpp-python
  con el MISMO renderizado → la medición del bake-off es idéntica a producción.

La pieza que antes divergía (renderizado del template con `enable_thinking` /
`low_effort` vía `Jinja2ChatFormatter`) vive aquí una sola vez; los fronts solo
deciden qué modo pedir.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import red_pill.core.model_runtime as mr

logger = logging.getLogger(__name__)

# Nombres registrados en el registry GLOBAL de llama_cpp (convención granite-*;
# el mapeo thinking→handler lo hace model_runtime.apply_thinking_to_template).
HANDLER_THINKING = "granite-thinking"
HANDLER_NOTHINK = "granite-nothink"
HANDLER_LOW = "granite-low"


def register_thinking_handlers(llm: Any, resolved: mr.ResolvedModel) -> None:
	"""Registra chat handlers por modo thinking derivados del template del GGUF.

	llama-cpp-python NO expone `chat_template_kwargs` en
	`create_chat_completion`; el `Jinja2ChatFormatter` acepta
	`enable_thinking`/`low_effort` vía kwargs. Cada modo queda registrado en el
	registry GLOBAL de llama_cpp como chat_format y el consumidor lo selecciona
	por request según el `thinking` resuelto. Al cargar un modelo nuevo se
	re-registran (solo hay UN modelo cargado a la vez).
	"""
	if not resolved.extra.get("thinking_supported", False):
		return
	try:
		import llama_cpp.llama_chat_format as lcf
		from llama_cpp.llama_chat_format import Jinja2ChatFormatter

		tpl = llm.metadata.get("tokenizer.chat_template", "")
		if not tpl:
			logger.warning("modelo sin tokenizer.chat_template — no se registran modos thinking")
			return
		eos_id = llm.token_eos()
		eos_str = llm._model.token_get_text(eos_id) if hasattr(llm._model, "token_get_text") else "<|im_end|>"
		bos_str = "<s>"

		def _mk(et: bool, le: bool = False, name: str = "") -> None:
			def fmt(*, messages: list, **kw: Any) -> Any:
				return Jinja2ChatFormatter(
					template=tpl, eos_token=eos_str, bos_token=bos_str,
					stop_token_ids=[eos_id],
				)(messages=messages, enable_thinking=et, low_effort=le, **kw)
			lcf.register_chat_format(name)(fmt)
			logger.debug("chat handler '%s' registrado (enable_thinking=%s, low_effort=%s)", name, et, le)

		_mk(True, False, HANDLER_THINKING)
		_mk(False, False, HANDLER_NOTHINK)
		_mk(True, True, HANDLER_LOW)
		logger.info("registrados chat handlers por modo thinking para '%s'", resolved.profile_name)
	except Exception as e:
		logger.error("no se pudieron registrar chat handlers thinking: %s", e)


def apply_chat_handler(llm: Any, resolved: mr.ResolvedModel, body: Optional[Dict[str, Any]] = None) -> None:
	"""Aplica el chat handler / chat_format correcto según la request.

	Orden: template nativo + thinking → handler registrado del modo; si el
	perfil declara `chat_format` explícito, gana el perfil (o el override del
	body). Un request con tools en un modelo sin handler thinking usa el
	chat_format nativo (llama_cpp autodetecta tools).
	"""
	body = body or {}
	thinking = body.get("thinking") or resolved.thinking or "off"
	handler_name = mr.apply_thinking_to_template(thinking)
	explicit = body.get("chat_format") or resolved.chat_format

	if handler_name and explicit is None and resolved.extra.get("thinking_supported"):
		llm.chat_format = handler_name
		return
	if explicit is not None:
		llm.chat_format = explicit
		return
	# Template nativo por defecto (chat_format=None → llama_cpp usa el del GGUF).
	llm.chat_format = None


def complete(model: Any, messages: list, **kwargs: Any) -> Any:
	"""Ejecuta una completion síncrona — la ejecución real compartida.

	El daemon la usa en el path no-stream (y en stream con iterador); el front
	CLI del bake-off la usa igual → medir aquí es medir producción.
	"""
	return model.create_chat_completion(messages=messages, stream=False, **kwargs)
