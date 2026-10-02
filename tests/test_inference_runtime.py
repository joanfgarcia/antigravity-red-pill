"""Inference runtime (RFC-HARNESS-002 v3) — núcleo común daemon/CLI.

Los handlers por modo thinking y la ejecución compartida viven en
`red_pill.inference.runtime`; el daemon y el front CLI del bake-off la importan.
Estos tests fijan el contrato de selección de chat_format por modo."""

from unittest.mock import MagicMock

import pytest

from red_pill.inference.runtime import apply_chat_handler, complete, renders_tool_role, tool_chat_format


def _resolved(thinking="off", chat_format=None, supported=False, minion_chat_format=None):
	r = MagicMock()
	r.thinking = thinking
	r.chat_format = chat_format
	r.minion_chat_format = minion_chat_format
	r.extra = {"thinking_supported": supported}
	return r


class FakeLlm:
	"""Lo mínimo de `llama_cpp.Llama` que toca apply_chat_handler (sin cargar modelo)."""

	def __init__(self, chat_handlers=None, chat_format="chatml"):
		self._chat_handlers = chat_handlers if chat_handlers is not None else {}
		self.chat_format = chat_format


_TOOLS = [{"type": "function", "function": {"name": "run_bash", "parameters": {}}}]


def test_apply_thinking_on_usa_handler_registrado():
	llm = MagicMock()
	r = _resolved(thinking="on", chat_format=None, supported=True)
	apply_chat_handler(llm, r, {"thinking": "on"})
	assert llm.chat_format == "granite-thinking"


def test_apply_thinking_off_usa_nothink():
	llm = MagicMock()
	r = _resolved(thinking="on", chat_format=None, supported=True)
	apply_chat_handler(llm, r, {"thinking": "off"})
	assert llm.chat_format == "granite-nothink"


def test_apply_chat_format_explicito_gana():
	# 4.1: chatml explícito en el perfil → gana sobre el handler thinking
	llm = MagicMock()
	r = _resolved(thinking="off", chat_format="chatml", supported=False)
	apply_chat_handler(llm, r, {"thinking": "off"})
	assert llm.chat_format == "chatml"


def test_apply_sin_handler_ni_explicito_usa_template_del_gguf():
	# Regresión: chat_format=None reventaba en request-time (perfil `smith`).
	llm = FakeLlm(chat_handlers={"chat_template.default": object()}, chat_format="granite-nothink")
	apply_chat_handler(llm, _resolved(thinking="off", chat_format=None, supported=False), {})
	assert llm.chat_format == "chat_template.default"


def test_apply_sin_template_en_el_gguf_cae_al_default_de_llama_cpp():
	llm = FakeLlm(chat_handlers={}, chat_format="chatml")
	apply_chat_handler(llm, _resolved(thinking="off", chat_format=None, supported=False), {})
	assert llm.chat_format == "llama-2"


def test_formato_nativo_resuelve_handler_en_request_time():
	# Mismo lookup que Llama.create_chat_completion: _chat_handlers → registry global.
	lcf = pytest.importorskip("llama_cpp.llama_chat_format")
	for handlers in ({"chat_template.default": object()}, {}):
		llm = FakeLlm(chat_handlers=handlers)
		apply_chat_handler(llm, _resolved(thinking="off", chat_format=None, supported=False), {})
		assert llm._chat_handlers.get(llm.chat_format) or lcf.get_chat_completion_handler(llm.chat_format)
	with pytest.raises(Exception):
		lcf.get_chat_completion_handler(None)


def test_tools_usa_minion_chat_format_del_perfil():
	llm = FakeLlm()
	r = _resolved(chat_format="chatml", minion_chat_format="chatml-function-calling")
	apply_chat_handler(llm, r, {"tools": _TOOLS})
	assert llm.chat_format == "chatml-function-calling"


def test_tools_con_thinking_usa_handler_nativo_del_modo():
	llm = FakeLlm()
	r = _resolved(thinking="on", supported=True)
	apply_chat_handler(llm, r, {"tools": _TOOLS, "thinking": "off"})
	assert llm.chat_format == "granite-nothink"
	apply_chat_handler(llm, r, {"tools": _TOOLS})
	assert llm.chat_format == "granite-thinking"


def test_tools_nunca_usa_el_chat_format_de_destilacion():
	# Regresión b49e93a0: el `chatml` del distiller descartaba los tools en silencio.
	llm = FakeLlm()
	r = _resolved(chat_format="chatml", supported=False)
	apply_chat_handler(llm, r, {"tools": _TOOLS})
	assert llm.chat_format == "chatml-function-calling"
	# también con `functions` (API legacy) y con override de chat_format en el body
	apply_chat_handler(llm, r, {"functions": [{"name": "f"}], "chat_format": "chatml"})
	assert llm.chat_format == "chatml-function-calling"


def test_tool_chat_format_y_rol_tool():
	assert tool_chat_format("chatml-function-calling", True, "on") == "chatml-function-calling"
	assert tool_chat_format(None, True, "low") == "granite-low"
	assert tool_chat_format(None, False, "on") == "chatml-function-calling"
	assert renders_tool_role("granite-thinking") and renders_tool_role("chat_template.default")
	assert not renders_tool_role("chatml-function-calling")


def test_complete_delega_en_create_chat_completion():
	model = MagicMock()
	model.create_chat_completion.return_value = {"choices": []}
	resp = complete(model, [{"role": "user", "content": "hola"}], max_tokens=5)
	assert resp == {"choices": []}
	model.create_chat_completion.assert_called_once()
	call = model.create_chat_completion.call_args
	assert call.kwargs["stream"] is False
	assert call.kwargs["max_tokens"] == 5


def test_register_thinking_handlers_noop_sin_soporte():
	from red_pill.inference.runtime import register_thinking_handlers

	llm = MagicMock()
	r = _resolved(supported=False)
	register_thinking_handlers(llm, r)  # no debe tocar llama_cpp
	llm.metadata.get.assert_not_called()
