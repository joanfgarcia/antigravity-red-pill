"""Provider de binarios de fork: modelos que llama-cpp-python NO puede cargar.

Motivo (2026-10-29): `bonsai_2_27b` es PTQ1_0; el venv no tiene ni una constante
PTQ y el daemon carga con `llama_cpp.Llama`, así que el modelo no entraba en
producción aunque estuviera medido y aprobado.

Estos tests no lanzan la GPU: mockean el proceso y el cliente HTTP. La prueba de
fuego real (arrancar el binario y servir el modelo) vive fuera de la suite.
"""

from types import SimpleNamespace

import pytest

from red_pill.core.providers import ForkServerInferenceProvider, provider_for_profile

MODELO = "/models/fake-27B.gguf"


@pytest.fixture(autouse=True)
def _limpia_vivos():
	ForkServerInferenceProvider._LIVE.clear()
	yield
	ForkServerInferenceProvider._LIVE.clear()


def _provider(**kw):
	kw.setdefault("n_ctx", 8192)
	return ForkServerInferenceProvider(MODELO, log_dir=None, **kw)


# ── Construcción del comando ────────────────────────────────────────────────


def test_comando_lleva_modelo_contexto_y_kv(monkeypatch):
	p = _provider(cache_type_k="q4_0", cache_type_v="q4_0", flash_attn=True, n_gpu_layers=-1)
	monkeypatch.setattr(p, "_server_binary", lambda: "/bin/llama-server")
	cmd = p._command(1234)
	texto = " ".join(cmd)
	assert "--model" in texto and MODELO in texto
	assert "-c 8192" in texto
	assert "-ctk q4_0" in texto and "-ctv q4_0" in texto
	assert "-fa on" in texto
	assert "-ngl -1" in texto
	assert "--jinja" in texto


def test_flash_attn_apagado_se_refleja(monkeypatch):
	p = _provider(flash_attn=False)
	monkeypatch.setattr(p, "_server_binary", lambda: "/bin/llama-server")
	assert "-fa off" in " ".join(p._command(1))


def test_extra_args_al_final(monkeypatch):
	p = _provider(extra_args=["--reasoning-budget", "0"])
	monkeypatch.setattr(p, "_server_binary", lambda: "/bin/llama-server")
	cmd = p._command(1)
	assert cmd[-2:] == ["--reasoning-budget", "0"]


def test_binario_ausente_falla_con_mensaje_util(monkeypatch):
	p = _provider(runtime_id="no_existe_este_runtime")
	with pytest.raises(RuntimeError) as exc:
		p._server_binary()
	assert "no_existe_este_runtime" in str(exc.value)


# ── Huella: cuándo hace falta relanzar ──────────────────────────────────────


def test_huella_cambia_con_la_conducta():
	base = _provider()._fingerprint
	assert _provider(n_ctx=4096)._fingerprint != base
	assert _provider(cache_type_k="q8_0")._fingerprint != base
	assert _provider(flash_attn=False)._fingerprint != base


def test_huella_estable_si_nada_cambia():
	assert _provider()._fingerprint == _provider()._fingerprint


# ── Ciclo de vida ───────────────────────────────────────────────────────────


def test_ensure_server_reutiliza_el_vivo(monkeypatch):
	p = _provider()
	monkeypatch.setattr(p, "_server_binary", lambda: "/bin/llama-server")
	llamadas = []
	monkeypatch.setattr(p, "_is_ready", lambda: True)
	monkeypatch.setattr(p, "_free_port", lambda: 1234)

	class _Proc:
		returncode = None

		def poll(self):
			return None

	def _popen(cmd, **kw):
		llamadas.append(cmd)
		return _Proc()

	import subprocess

	monkeypatch.setattr(subprocess, "Popen", _popen)
	p.ensure_server()
	p.ensure_server()
	assert len(llamadas) == 1, "el segundo ensure_server no debe relanzar"


def test_stop_mata_el_proceso(monkeypatch):
	p = _provider()
	visto = {}

	class _Proc:
		returncode = None

		def poll(self):
			return self.returncode

		def terminate(self):
			visto["terminate"] = True
			self.returncode = 0

		def wait(self, timeout=None):
			return 0

	p._process = _Proc()
	p.stop()
	assert visto.get("terminate") is True
	assert p._process is None


# ── Chat ────────────────────────────────────────────────────────────────────


def test_chat_devuelve_el_message(monkeypatch):
	p = _provider()
	monkeypatch.setattr(p, "ensure_server", lambda: None)
	p._port = 1234
	capturado = {}

	class _Resp:
		def raise_for_status(self):
			return None

		def json(self):
			return {"choices": [{"message": {"content": "ok", "tool_calls": [{"id": "1"}]}}]}

	class _Client:
		def __init__(self, *a, **k):
			pass

		def __enter__(self):
			return self

		def __exit__(self, *a):
			return False

		def post(self, url, json=None):
			capturado["url"] = url
			capturado["payload"] = json
			return _Resp()

	import httpx

	monkeypatch.setattr(httpx, "Client", _Client)
	msg = p.chat([{"role": "user", "content": "hola"}], tools=[{"type": "function"}], max_tokens=64)
	assert msg["content"] == "ok"
	assert msg["tool_calls"][0]["id"] == "1"
	assert capturado["url"].endswith("/v1/chat/completions")
	assert capturado["payload"]["tools"]


# ── Elección de provider por perfil ─────────────────────────────────────────


def test_perfil_fork_usa_servidor_de_binario(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp_fork"}))
	resolved = SimpleNamespace(model_path=MODELO, runtime="llama_cpp_prism", n_ctx=4096,
	                           n_gpu_layers=-1, flash_attn="auto")
	assert isinstance(provider_for_profile(resolved), ForkServerInferenceProvider)


def test_perfil_stock_no_construye_provider(monkeypatch):
	from red_pill.core import runtime_registry as rr

	monkeypatch.setattr(rr.RuntimeRegistry, "get", classmethod(lambda cls, rid, variant=None: {"kind": "llama_cpp"}))
	resolved = SimpleNamespace(model_path=MODELO, runtime="llama_cpp_stock", n_ctx=4096,
	                           n_gpu_layers=-1, flash_attn="auto")
	assert provider_for_profile(resolved) is None, "el camino stock no construye provider"
