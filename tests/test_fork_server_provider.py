"""Provider de perfiles anclados a runtime de fork (PTQ1_0, PQ2_0, i2_s).

Motivo (2026-10-29): `bonsai_2_27b` es PTQ1_0; `llama-cpp-python` no tiene ni una
constante PTQ, así que el modelo no podía entrar en producción aunque estuviera
medido y aprobado.

El provider es un **adaptador**: el ciclo de vida lo lleva `RuntimeServer` (AD-049),
que resuelve modelo, contexto y plan de KV desde el perfil. Aquí se fija el
contrato, no la implementación del servidor.
"""

from types import SimpleNamespace

import pytest

from red_pill.core.providers import ForkServerInferenceProvider, provider_for_profile


class _FakeServer:
	"""RuntimeServer mínimo: registra llamadas y devuelve una respuesta fija."""

	def __init__(self, calls):
		self.calls = calls
		self._running = True

	def is_running(self):
		return self._running

	def chat(self, messages, **kwargs):
		self.calls.append({"messages": messages, **kwargs})
		return {"choices": [{"message": {"content": "ok", "tool_calls": [{"id": "c1"}]}}]}

	def stop(self):
		self.calls.append({"stopped": True})
		self._running = False


@pytest.fixture
def fake_runtime(monkeypatch):
	"""Sustituye RuntimeServer por el falso, espiando los argumentos de construcción."""
	from red_pill.inference import runtime_server as rs

	construidos = []
	calls = []

	class _Factory:
		def __init__(self, profile_name, **kwargs):
			construidos.append({"profile_name": profile_name, **kwargs})
			self._server = _FakeServer(calls)

		def start(self):
			self._server.calls.append({"started": True})
			return self._server

	construidos.clear()
	calls.clear()
	monkeypatch.setattr(rs, "RuntimeServer", _Factory)
	return SimpleNamespace(construidos=construidos, calls=calls)


# ── Adaptador ───────────────────────────────────────────────────────────────


def test_arranca_desde_el_perfil_no_desde_una_ruta(fake_runtime):
	p = ForkServerInferenceProvider("bonsai_2_27b")
	p.generate("hola")
	assert fake_runtime.construidos[0]["profile_name"] == "bonsai_2_27b"


def test_server_idempotente(fake_runtime):
	p = ForkServerInferenceProvider("bonsai_2_27b")
	p.generate("uno")
	p.generate("dos")
	assert len(fake_runtime.construidos) == 1, "el segundo generate reutiliza el servidor"
	assert sum(1 for c in fake_runtime.calls if c.get("started")) == 1


def test_chat_devuelve_el_message_y_pasa_tools(fake_runtime):
	p = ForkServerInferenceProvider("bonsai_2_27b")
	msg = p.chat(
		[{"role": "user", "content": "hola"}],
		tools=[{"type": "function", "function": {"name": "f"}}],
		tool_choice="auto",
		max_tokens=64,
	)
	assert msg["content"] == "ok"
	assert msg["tool_calls"][0]["id"] == "c1"
	llamada = [c for c in fake_runtime.calls if "messages" in c][0]
	assert llamada["tools"], "los tools tienen que llegar al servidor (carril minion_tool)"
	assert llamada["tool_choice"] == "auto"
	assert llamada["max_tokens"] == 64


def test_stop_para_el_servidor(fake_runtime):
	p = ForkServerInferenceProvider("bonsai_2_27b")
	p.generate("hola")
	p.stop()
	assert any(c.get("stopped") for c in fake_runtime.calls)
	assert p._srv is None


def test_rearranca_tras_stop(fake_runtime):
	p = ForkServerInferenceProvider("bonsai_2_27b")
	p.generate("uno")
	p.stop()
	p.generate("dos")
	assert len(fake_runtime.construidos) == 2


def test_is_available_false_si_el_runtime_no_esta(monkeypatch):
	from red_pill.inference import runtime_server as rs

	class _Boom:
		def __init__(self, *a, **k):
			raise RuntimeError("runtime no declarado")

	monkeypatch.setattr(rs, "RuntimeServer", _Boom)
	assert ForkServerInferenceProvider("no_existe").is_available() is False


# ── Elección por perfil ─────────────────────────────────────────────────────


def test_perfil_fork_devuelve_adaptador(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	resolved = SimpleNamespace(profile_name="bonsai_2_27b", runtime="llama_cpp_prism", n_ctx=16384)
	assert isinstance(provider_for_profile(resolved), ForkServerInferenceProvider)


def test_perfil_fork_sin_profile_name_falla_claro(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	resolved = SimpleNamespace(runtime="llama_cpp_prism", n_ctx=16384)
	with pytest.raises(RuntimeError) as exc:
		provider_for_profile(resolved)
	assert "profile_name" in str(exc.value)


def test_perfil_stock_no_construye_provider(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp"}))
	resolved = SimpleNamespace(profile_name="granite_8b", runtime="llama_cpp_stock", n_ctx=4096)
	assert provider_for_profile(resolved) is None
