"""Inference runtime (RFC-HARNESS-002 v3) — núcleo común daemon/CLI.

Los handlers por modo thinking y la ejecución compartida viven en
`red_pill.inference.runtime`; el daemon y el front CLI del bake-off la importan.
Estos tests fijan el contrato de selección de chat_format por modo."""

from unittest.mock import MagicMock

from red_pill.inference.runtime import apply_chat_handler, complete


def _resolved(thinking="off", chat_format=None, supported=False):
	r = MagicMock()
	r.thinking = thinking
	r.chat_format = chat_format
	r.extra = {"thinking_supported": supported}
	return r


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


def test_apply_sin_handler_ni_explicito_native():
	llm = MagicMock()
	r = _resolved(thinking="off", chat_format=None, supported=False)
	apply_chat_handler(llm, r, {})
	assert llm.chat_format is None


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
