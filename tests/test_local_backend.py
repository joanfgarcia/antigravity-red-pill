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


# ── extra_server_args: configuración, no código ─────────────────────────────


def test_extra_server_args_del_perfil_llegan_al_servidor(monkeypatch):
	"""Las peculiaridades de un modelo se declaran en el perfil, no en el código."""
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	creados = []

	class _Srv:
		base_url = "http://x:1"

		def __init__(self, profile_name, **kw):
			creados.append(kw)

		def start(self):
			return self

	resolved = SimpleNamespace(
		profile_name="bonsai_2_27b", runtime_id="llama_cpp_prism", n_ctx=4096,
		thinking="off",
		extra_server_args=["--reasoning", "off", "--reasoning-budget", "0", "--kv-mean-center", "x.gguf"],
	)
	build_local_backend(resolved, server_factory=_Srv)
	assert creados[0]["extra_args"] == [
		"--reasoning", "off", "--reasoning-budget", "0", "--kv-mean-center", "x.gguf"
	]


def test_sin_extra_server_args_inyecta_y_avisa(monkeypatch):
	"""Red de seguridad: perfil con thinking off y sin flags → se inyecta."""
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	creados = []

	class _Srv:
		base_url = "http://x:1"

		def __init__(self, profile_name, **kw):
			creados.append(kw)

		def start(self):
			return self

	resolved = SimpleNamespace(profile_name="olvidado", runtime_id="llama_cpp_prism", n_ctx=4096, thinking="off")
	build_local_backend(resolved, server_factory=_Srv)
	assert "--reasoning" in creados[0]["extra_args"]


class _FakeLlama:
	creados: list = []

	def __init__(self, **kw):
		_FakeLlama.creados.append(kw)


def _en_proceso(monkeypatch):
	import sys
	import types

	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp"}))
	monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=_FakeLlama))
	_FakeLlama.creados = []
	return SimpleNamespace(
		profile_name="granite_8b",
		model_path="/m.gguf",
		chat_format=None,
		n_ctx=8192,
		n_gpu_layers=-1,
		flash_attn="true",
		extra={},
	)


def test_en_proceso_respeta_lo_que_decide_el_daemon(monkeypatch):
	"""Regresión de 8d78450: el worker de CPU cargaba con las capas y el contexto
	del perfil de GPU, y el `flash_attn` del perfil no llegaba a `Llama()`."""
	resolved = _en_proceso(monkeypatch)
	build_local_backend(resolved, n_ctx=2048, n_gpu_layers=0, flash_attn=False)
	kw = _FakeLlama.creados[0]
	assert (kw["n_ctx"], kw["n_gpu_layers"], kw["flash_attn"]) == (2048, 0, False)


def test_en_proceso_sin_argumentos_usa_el_perfil(monkeypatch):
	resolved = _en_proceso(monkeypatch)
	build_local_backend(resolved)
	kw = _FakeLlama.creados[0]
	assert (kw["n_ctx"], kw["n_gpu_layers"], kw["flash_attn"]) == (8192, -1, True), "flash_attn: true del perfil en GPU"
