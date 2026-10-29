"""Backend local uniforme: el daemon no ramifica por motor.

El daemon sólo usa `tokenize` y `create_chat_completion`. Este módulo los sirve
igual para un modelo en proceso que para el binario de un fork, así que cambiar
de motor no obliga a tocar el daemon.
"""

import json
from types import SimpleNamespace

import pytest

from red_pill.inference.local_backend import ForkChatBackend, build_local_backend


class _FakeServer:
	base_url = "http://127.0.0.1:9"

	def __init__(self, respuestas=None):
		self.respuestas = respuestas or []
		self.vistos = []
		self.stopped = False

	def stop(self):
		self.stopped = True


class _Resp:
	def __init__(self, payload=None, lineas=None):
		self._payload = payload
		self._lineas = lineas or []

	def __enter__(self):
		return self

	def __exit__(self, *a):
		return False

	def read(self):
		return json.dumps(self._payload).encode()

	def __iter__(self):
		return iter(self._lineas)


# ── ForkChatBackend ─────────────────────────────────────────────────────────


def test_tokenize_parsea_tokens(monkeypatch):
	b = ForkChatBackend(_FakeServer())
	monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp({"tokens": [7, 42]}))
	assert b.tokenize("hola") == [7, 42]


def test_tokenize_falla_suave(monkeypatch):
	def _boom(req, timeout=None):
		raise OSError("servidor caído")

	monkeypatch.setattr("urllib.request.urlopen", _boom)
	assert ForkChatBackend(_FakeServer()).tokenize("hola") == []


def test_chat_descarta_claves_de_proceso(monkeypatch):
	visto = {}

	def _urlopen(req, timeout=None):
		visto["body"] = json.loads(req.data.decode())
		return _Resp({"choices": [{"message": {"content": "ok"}}]})

	monkeypatch.setattr("urllib.request.urlopen", _urlopen)
	out = ForkChatBackend(_FakeServer()).create_chat_completion(
		[{"role": "user", "content": "hola"}],
		chat_format="chatml",          # sólo tiene sentido en proceso
		grammar=None,                  # None se descarta
		max_tokens=32,
	)
	assert out["choices"][0]["message"]["content"] == "ok"
	assert "chat_format" not in visto["body"], "las claves de llama-cpp no viajan por HTTP"
	assert "grammar" not in visto["body"]
	assert visto["body"]["max_tokens"] == 32


def test_stream_traduce_sse(monkeypatch):
	lineas = [
		b'data: {"choices":[{"delta":{"content":"ho"}}]}\n',
		b'data: {"choices":[{"delta":{"content":"la"}}]}\n',
		b"data: [DONE]\n",
	]
	monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(lineas=lineas))
	chunks = list(ForkChatBackend(_FakeServer()).create_chat_completion([{"role": "user", "content": "x"}], stream=True))
	assert len(chunks) == 2
	assert chunks[0]["choices"][0]["delta"]["content"] == "ho"


# ── Elección de backend ─────────────────────────────────────────────────────


def test_perfil_fork_devuelve_backend_http(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	creados = []

	class _Srv:
		base_url = "http://x:1"

		def __init__(self, profile_name, **kw):
			creados.append((profile_name, kw))

		def start(self):
			return self

	resolved = SimpleNamespace(profile_name="bonsai_2_27b", runtime="llama_cpp_prism", n_ctx=4096)
	backend = build_local_backend(resolved, server_factory=_Srv)
	assert isinstance(backend, ForkChatBackend)
	assert creados[0][0] == "bonsai_2_27b"


def test_perfil_fork_sin_nombre_falla(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	with pytest.raises(RuntimeError):
		build_local_backend(SimpleNamespace(runtime="llama_cpp_prism", n_ctx=4096), server_factory=lambda *a, **k: None)
