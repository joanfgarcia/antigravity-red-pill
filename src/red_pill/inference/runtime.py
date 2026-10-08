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
from pathlib import Path
from typing import Any, Dict, Optional

import red_pill.core.model_runtime as mr

logger = logging.getLogger(__name__)

# Nombres registrados en el registry GLOBAL de llama_cpp (convención granite-*;
# el mapeo thinking→handler lo hace model_runtime.apply_thinking_to_template).
HANDLER_THINKING = "granite-thinking"
HANDLER_NOTHINK = "granite-nothink"
HANDLER_LOW = "granite-low"

# Generic llama_cpp function-calling formatter. Used when a request carries
# tools but the profile declares no explicit `minion_chat_format` and the model
# has no native thinking handler. Empirically Granite-4.1-Q4 emits valid
# OpenAI tool_calls through it (bake-off 2026-09-30).
TOOL_CHAT_FALLBACK = "chatml-function-calling"

# Al cargar, llama_cpp registra el template del GGUF en `llm._chat_handlers`
# con este nombre; sin template su propio default es `llama-2`. `chat_format=None`
# NO vale en request-time (llama_cpp>=0.3: get_chat_completion_handler(None)
# lanza), así que "template nativo" se traduce a uno de estos dos.
NATIVE_TEMPLATE_FORMAT = "chat_template.default"
LLAMA_CPP_DEFAULT_FORMAT = "llama-2"

# Handlers que renderizan con el template NATIVO del GGUF. El de Granite 4.2
# tiene rol `tool` (lo envuelve en `<tool_response>` dentro de un turno user);
# `chatml-function-calling` no tiene rama `tool` y lo descarta en silencio.
NATIVE_TOOL_HANDLERS = (HANDLER_THINKING, HANDLER_NOTHINK, HANDLER_LOW, NATIVE_TEMPLATE_FORMAT)


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
					template=tpl,
					eos_token=eos_str,
					bos_token=bos_str,
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


def tool_chat_format(minion_chat_format: Optional[str], thinking_supported: bool, thinking: str = "off") -> str:
	"""chat_format que sirve una request CON tools — fuente única daemon/cliente.

	`minion_chat_format` del perfil → handler nativo del modo thinking (su
	template Jinja renderiza tools) → `chatml-function-calling` genérico. El
	`chat_format` de destilación NUNCA se usa con tools (los descarta en
	silencio). El cliente (`local_minion`) lo consulta para saber cómo
	realimentar los resultados (`renders_tool_role`).
	"""
	if minion_chat_format:
		return minion_chat_format
	handler_name = mr.apply_thinking_to_template(thinking)
	if handler_name and thinking_supported:
		return handler_name
	return TOOL_CHAT_FALLBACK


def renders_tool_role(chat_format: str) -> bool:
	"""¿El handler renderiza mensajes `role="tool"`? Solo el template nativo del GGUF."""
	return chat_format in NATIVE_TOOL_HANDLERS


def _native_chat_format(llm: Any) -> str:
	"""chat_format del template nativo del GGUF (o el default de llama_cpp sin template)."""
	handlers = getattr(llm, "_chat_handlers", None)
	if isinstance(handlers, dict) and NATIVE_TEMPLATE_FORMAT in handlers:
		return NATIVE_TEMPLATE_FORMAT
	return LLAMA_CPP_DEFAULT_FORMAT


def register_file_template(llm: Any, resolved: mr.ResolvedModel) -> Optional[str]:
	"""Registra el `chat_template_file` del perfil como handler (una vez por llm).

	El template embebido del GGUF puede estar roto (jinja con `selectattr`, p.ej.
	Mistral-Nemo mradermacher); el perfil declara su plantilla simple y aquí se
	convierte en handler de llama-cpp-python — misma vía para daemon y runners.
	"""
	tpl_ref = getattr(resolved, "chat_template_file", None)
	if not tpl_ref:
		return None
	name = f"profile-template-{resolved.profile_name}"
	if getattr(llm, "_rp_file_template_registered", None) == name:
		return name
	try:
		from llama_cpp.llama_chat_format import Jinja2ChatFormatter, register_chat_format

		from red_pill.core.paths import get_bunker_root

		tpl_path = Path(tpl_ref)
		if not tpl_path.is_absolute():
			tpl_path = get_bunker_root() / tpl_path
		template = tpl_path.read_text(encoding="utf-8")
		eos_id = llm.token_eos()
		eos_str = llm._model.token_get_text(eos_id) if hasattr(llm._model, "token_get_text") else "<|im_end|>"

		def fmt(*, messages: list, **kw: Any) -> Any:
			return Jinja2ChatFormatter(template=template, eos_token=eos_str, bos_token="<s>", stop_token_ids=[eos_id])(messages=messages, **kw)

		register_chat_format(name)(fmt)
		llm._rp_file_template_registered = name
		logger.info("chat handler '%s' registrado desde %s", name, tpl_path)
		return name
	except Exception as e:
		if "already registered" in str(e):
			# Registro global previo (mismo nombre, otro llm en el proceso): se reutiliza.
			llm._rp_file_template_registered = name
			return name
		logger.error("no se pudo registrar el chat_template_file de '%s': %s", resolved.profile_name, e)
		return None


def apply_chat_handler(llm: Any, resolved: mr.ResolvedModel, body: Optional[Dict[str, Any]] = None) -> None:
	"""Aplica el chat handler / chat_format correcto según la request.

	Orden para requests SIN tools: template nativo + thinking → handler
	registrado del modo; si el perfil declara `chat_format` explícito, gana el
	perfil (o el override del body); sin ninguno, el template del GGUF.

	Requests CON tools (`tools`/`functions`): ver `tool_chat_format`.
	"""
	body = body or {}
	wants_tools = bool(body.get("tools") or body.get("functions"))
	thinking = body.get("thinking") or resolved.thinking or "off"
	handler_name = mr.apply_thinking_to_template(thinking)
	explicit = body.get("chat_format") or resolved.chat_format

	# Tool requests MUST use a tool-capable handler. The profile `chat_format`
	# (the distiller template, e.g. "chatml") silently drops the `tools` — the
	# model then answers in prose, or invents a tool and fabricates its output.
	if wants_tools:
		llm.chat_format = tool_chat_format(resolved.minion_chat_format, bool(resolved.extra.get("thinking_supported")), thinking)
		return

	# Override explícito del body, y luego la plantilla declarada por el perfil
	# (chat_template_file): el template embebido roto no debe decidir nunca.
	if body.get("chat_format"):
		llm.chat_format = body["chat_format"]
		return
	file_handler = register_file_template(llm, resolved)
	if file_handler:
		llm.chat_format = file_handler
		return

	if handler_name and explicit is None and resolved.extra.get("thinking_supported"):
		llm.chat_format = handler_name
		return
	if explicit is not None:
		llm.chat_format = explicit
		return
	# Template nativo por defecto. NO `None`: llama_cpp solo lo resuelve al
	# cargar; en request-time get_chat_completion_handler(None) lanza (perfiles
	# sin chat_format ni thinking, p. ej. `smith`).
	llm.chat_format = _native_chat_format(llm)


def complete(model: Any, messages: list, **kwargs: Any) -> Any:
	"""Ejecuta una completion síncrona — la ejecución real compartida.

	El daemon la usa en el path no-stream (y en stream con iterador); el front
	CLI del bake-off la usa igual → medir aquí es medir producción.
	"""
	return model.create_chat_completion(messages=messages, stream=False, **kwargs)
