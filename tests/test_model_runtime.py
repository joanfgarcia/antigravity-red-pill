"""RFC-HARNESS-002 — servicio de gobierno de la inferencia local (model_runtime)."""

from red_pill.core.model_runtime import extract_thinking, extract_toolcalls


def test_extract_toolcalls_qwen():
	text = 'razonamiento <tool_call>{"function": "search", "arguments": {"q": "hola"}}</tool_call> fin'
	calls = extract_toolcalls(text, tool_format="qwen")
	assert len(calls) == 1
	assert calls[0]["function"]["name"] == "search"
	assert calls[0]["function"]["arguments"] == {"q": "hola"}


def test_extract_toolcalls_vacio():
	assert extract_toolcalls("sin tool call", tool_format="qwen") == []
	assert extract_toolcalls("", tool_format="auto") == []


def test_extract_toolcalls_openai():
	text = '{"type": "function", "function": {"name": "f", "arguments": "{\\"x\\": 1}"}}'
	calls = extract_toolcalls(text, tool_format="openai")
	assert len(calls) == 1 and calls[0]["function"]["name"] == "f"
	assert calls[0]["function"]["arguments"] == {"x": 1}


def test_extract_thinking():
	thinking, answer = extract_thinking("paso a paso response la respuesta")
	assert "paso a paso" in thinking
	assert "la respuesta" in answer
	# sin marcador → todo es respuesta
	thinking2, answer2 = extract_thinking("solo respuesta")
	assert thinking2 == ""
	assert "solo respuesta" in answer2


def test_resolve_rechaza_experimental_y_custom_juntos():
	from red_pill.core.model_runtime import ModelRuntimeConfigError, resolve

	try:
		resolve({"experimental": {}, "custom": {}})
		assert False, "debe lanzar"
	except ModelRuntimeConfigError:
		pass


def test_resolve_sin_nada_lanza_config_error():
	from red_pill.core.model_runtime import ModelRuntimeConfigError, resolve

	try:
		resolve({})
		assert False, "debe lanzar (sin modelo/task/default)"
	except ModelRuntimeConfigError:
		pass
