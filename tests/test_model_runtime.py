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


def test_extract_toolcalls_devuelve_todas_las_llamadas_en_orden():
	# Regresión: `re.search` devolvía solo la primera y descartaba el resto en silencio.
	text = (
		"<tool_call>\n<function=run_bash>\n<parameter=command>\nls\n</parameter>\n</function>\n</tool_call>\n"
		'<tool_call>{"name": "bunker_memory_api", "arguments": {"action": "a", "payload": {}}}</tool_call>'
	)
	calls = extract_toolcalls(text, tool_format="qwen")
	assert [c["function"]["name"] for c in calls] == ["run_bash", "bunker_memory_api"]
	assert calls[1]["function"]["arguments"] == {"action": "a", "payload": {}}
	two = '[{"type": "function", "function": {"name": "f", "arguments": {}}}, {"type": "function", "function": {"name": "g"}}]'
	assert [c["function"]["name"] for c in extract_toolcalls(two, tool_format="openai")] == ["f", "g"]


def test_extract_toolcalls_omite_bloque_ilegible():
	text = "<tool_call>basura sin formato</tool_call><tool_call><function=run_bash></function></tool_call>"
	calls = extract_toolcalls(text, tool_format="qwen")
	assert [c["function"]["name"] for c in calls] == ["run_bash"]
	# bloque truncado (sin cierre) → no es una llamada
	assert extract_toolcalls("<tool_call>\n<function=run_bash>\n<parameter=command>\nrm", tool_format="qwen") == []


def test_extract_toolcalls_arguments_string_json():
	# Regresión: arguments como string JSON (convención OpenAI) se descartaba → {}.
	text = '<tool_call>{"name": "run_bash", "arguments": "{\\"command\\": \\"ls\\"}"}</tool_call>'
	calls = extract_toolcalls(text, tool_format="qwen")
	assert calls[0]["function"]["arguments"] == {"command": "ls"}
	# string ilegible o no-objeto → {} (siempre mapping)
	bad = '<tool_call>{"name": "run_bash", "arguments": "no es json"}</tool_call>'
	assert extract_toolcalls(bad, tool_format="qwen")[0]["function"]["arguments"] == {}
	nulo = '{"type": "function", "function": {"name": "f", "arguments": null}}'
	assert extract_toolcalls(nulo, tool_format="openai")[0]["function"]["arguments"] == {}


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
