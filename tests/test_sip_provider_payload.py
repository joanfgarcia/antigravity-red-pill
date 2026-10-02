"""SIP provider: el payload NO manda `model` si está vacío (fix 2026-09-28).

Un `model` inválido tiene prioridad sobre `task` en el selector (AD-030) y
tumbaba la síntesis de hubs con HTTP 500 (glob muerto `*Q4_K_M.gguf`).
"""

import pytest

from red_pill.core.providers import SipInferenceError, SipInferenceProvider


def test_payload_omite_model_si_vacio():
	p = SipInferenceProvider(socket_path="/tmp/no.sock")
	pl = p._build_payload(task="conversation", messages=[{"role": "user", "content": "hi"}], temperature=0.3)
	assert "model" not in pl
	assert pl["task"] == "conversation"
	assert pl["temperature"] == 0.3


def test_payload_incluye_model_si_set():
	p = SipInferenceProvider(socket_path="/tmp/no.sock", model="granite_8b")
	pl = p._build_payload(task="conversation", messages=[], temperature=0.1)
	assert pl["model"] == "granite_8b"


def test_payload_extra_solo_si_presentes():
	p = SipInferenceProvider(socket_path="/tmp/no.sock")
	pl = p._build_payload(task="minion_tool", messages=[], temperature=0.2, max_tokens=8, stop=None, tools=[{"x": 1}])
	assert pl["max_tokens"] == 8
	assert "stop" not in pl
	assert pl["tools"] == [{"x": 1}]


def test_default_model_es_vacio():
	# No debe reaparecer el wildcard muerto.
	assert SipInferenceProvider(socket_path="/tmp/no.sock").model == ""


def _serve_once(sock_path, status, body):
	"""Servidor HTTP mínimo sobre UDS: atiende UNA petición y guarda su payload."""
	import json
	import socket
	import threading

	server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	server.bind(sock_path)
	server.listen(1)
	seen = {}

	def _handle():
		conn, _ = server.accept()
		with conn:
			data = b""
			while b"\r\n\r\n" not in data:
				data += conn.recv(65536)
			head, _, rest = data.partition(b"\r\n\r\n")
			length = next(int(h.split(b":", 1)[1]) for h in head.split(b"\r\n") if h.lower().startswith(b"content-length"))
			while len(rest) < length:
				rest += conn.recv(65536)
			seen["payload"] = json.loads(rest)
			raw = body.encode()
			conn.sendall(
				f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw
			)
		server.close()

	threading.Thread(target=_handle, daemon=True).start()
	return seen


def test_chat_aflora_el_error_del_daemon(tmp_path):
	# Regresión: un 400 del daemon ({"error": ...}) reventaba con KeyError 'choices'.
	sock = str(tmp_path / "sip.sock")
	_serve_once(sock, 400, '{"error": "model \'granite_4_2_8b\' no es candidato de la task \'minion_tool\' (K1)"}')
	with pytest.raises(SipInferenceError) as exc:
		SipInferenceProvider(socket_path=sock, model="granite_4_2_8b").chat([{"role": "user", "content": "hi"}], timeout=5)
	assert "HTTP 400" in str(exc.value) and "K1" in str(exc.value)


def test_chat_respuesta_no_json_es_error_claro(tmp_path):
	sock = str(tmp_path / "sip.sock")
	_serve_once(sock, 502, "Bad Gateway")
	with pytest.raises(SipInferenceError, match="HTTP 502.*Bad Gateway"):
		SipInferenceProvider(socket_path=sock).chat([{"role": "user", "content": "hi"}], timeout=5)


def test_chat_devuelve_el_mensaje_y_reenvia_la_conducta(tmp_path):
	sock = str(tmp_path / "sip.sock")
	seen = _serve_once(sock, 200, '{"choices": [{"message": {"role": "assistant", "content": "ok"}}]}')
	msg = SipInferenceProvider(socket_path=sock).chat(
		[{"role": "user", "content": "hi"}], tools=[{"x": 1}], tool_choice="auto", temperature=1.0, max_tokens=2048, timeout=5
	)
	assert msg == {"role": "assistant", "content": "ok"}
	assert seen["payload"]["task"] == "minion_tool"
	assert seen["payload"]["temperature"] == 1.0 and seen["payload"]["max_tokens"] == 2048
