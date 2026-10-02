"""RFC-HARNESS-002 — servicio de gobierno de la inferencia local (model_runtime)."""

from red_pill.core.model_runtime import extract_thinking, extract_toolcalls


def test_extract_toolcalls_qwen():
	text = 'razonamiento <tool_call>{"function": "search", "arguments": {"q": "hola"}}</tool_call> fin'
	calls = extract_toolcalls(text, tool_format="qwen")
	assert len(calls) == 1
	assert calls[0]["function"]["name"] == "search"
	assert calls[0]["function"]["arguments"] == {"q": "hola"}


def test_extract_toolcalls_granite_native():
	# Salida nativa real de Granite 4.2 (template Jinja, no handler estructurado):
	# <tool_call><function=NAME><parameter=k>v</parameter></function></tool_call>
	text = (
		"<think>Debo leer el fichero.</think>\n"
		"<tool_call>\n<function=run_bash>\n<parameter=command>\n"
		"cat manifest.txt\n</parameter>\n</function>\n</tool_call>"
	)
	calls = extract_toolcalls(text, tool_format="qwen")
	assert len(calls) == 1
	assert calls[0]["function"]["name"] == "run_bash"
	assert calls[0]["function"]["arguments"] == {"command": "cat manifest.txt"}


def test_extract_toolcalls_vacio():
	assert extract_toolcalls("sin tool call", tool_format="qwen") == []
	assert extract_toolcalls("", tool_format="auto") == []


def test_extract_toolcalls_openai():
	text = '{"type": "function", "function": {"name": "f", "arguments": "{\\"x\\": 1}"}}'
	calls = extract_toolcalls(text, tool_format="openai")
	assert len(calls) == 1 and calls[0]["function"]["name"] == "f"
	assert calls[0]["function"]["arguments"] == {"x": 1}


def test_extract_thinking():
	thinking, answer = extract_thinking("paso a paso</think>la respuesta")
	assert thinking == "paso a paso"
	assert answer == "la respuesta"
	# con apertura explícita
	thinking, answer = extract_thinking("<think>\nrazono\n</think>\n\nAnswer: 42")
	assert (thinking, answer) == ("razono", "Answer: 42")
	# sin marcador → todo es respuesta
	thinking2, answer2 = extract_thinking("solo respuesta")
	assert thinking2 == ""
	assert "solo respuesta" in answer2


def test_extract_thinking_no_parte_por_palabras_de_la_prosa():
	# Regresión: la regex vieja partía por la palabra "response" en cualquier sitio.
	for prose in ("The HTTP response code was 200", "No responses found", "Response time: 3s"):
		assert extract_thinking(prose) == ("", prose)
	thinking, answer = extract_thinking("<think>I should write a response</think>Answer: 42")
	assert thinking == "I should write a response"
	assert answer == "Answer: 42"


def test_extract_thinking_sin_cerrar_y_cli():
	# Presupuesto agotado razonando: nada del razonamiento se filtra como respuesta.
	assert extract_thinking("<think>sigo pensando y me corto") == ("sigo pensando y me corto", "")
	assert extract_thinking("[Start thinking]razono[End thinking]\n{\"ok\": 1}") == ("razono", '{"ok": 1}')


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
