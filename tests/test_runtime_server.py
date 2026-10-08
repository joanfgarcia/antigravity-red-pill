"""TST-RS-001: RuntimeServer — servidor dedicado por runtime (RFC-HARNESS-003 corte 2).

Tests herméticos: sin GPU, sin proceso real (se inyectan fakes de Popen/urlopen)
y sin tocar la config del operador (se monkeypatchean ModelRegistry y
RuntimeRegistry en el namespace del módulo).
"""

import json
import os

import pytest


class _FakeProc:
	def __init__(self, poll_sequence=None):
		self.poll_sequence = list(poll_sequence or [None])
		self.terminated = False
		self.killed = False
		self.waited = False
		self.returncode = None
		self.pid = os.getpid()

	def poll(self):
		if len(self.poll_sequence) > 1:
			return self.poll_sequence.pop(0)
		return self.poll_sequence[0]

	def terminate(self):
		self.terminated = True
		self.poll_sequence = [0]

	def kill(self):
		self.killed = True
		self.poll_sequence = [0]

	def wait(self, timeout=None):
		self.waited = True
		return 0


class _FakeRuntimeRegistry:
	runtime = {
		"id": "llama_cpp_prism",
		"server": "/fake/prism/llama-server",
		"binary": "/fake/prism/llama-cli",
	}
	fail = False

	@classmethod
	def require(cls, runtime_id):
		if cls.fail:
			from red_pill.core.runtime_registry import RuntimeUnavailableError

			raise RuntimeUnavailableError(f"[RUNTIME] runtime '{runtime_id}' no disponible (fake)")
		return dict(cls.runtime)

	@classmethod
	def for_profile(cls, profile):
		return dict(cls.runtime)

	@classmethod
	def default_id(cls):
		return "llama_cpp_stock"


class _FakeModelRegistry:
	profiles = {}
	hardware = {"n_ctx": 24576, "n_gpu_layers": -1}
	kv_plan = {}

	@classmethod
	def get_profile(cls, name):
		return dict(cls.profiles.get(name, {}))

	@classmethod
	def get_resolved_hardware_affinity(cls, name):
		return dict(cls.hardware)

	@classmethod
	def plan_kv_cache(cls, name, ctx=None, free_mb=None):
		return dict(cls.kv_plan)


@pytest.fixture
def mod(monkeypatch):
	import red_pill.inference.runtime_server as rs

	monkeypatch.setattr(rs, "ModelRegistry", _FakeModelRegistry)
	monkeypatch.setattr(rs, "RuntimeRegistry", _FakeRuntimeRegistry)
	_FakeRuntimeRegistry.fail = False
	_FakeRuntimeRegistry.runtime = {
		"id": "llama_cpp_prism",
		"server": "/fake/prism/llama-server",
		"binary": "/fake/prism/llama-cli",
	}
	_FakeModelRegistry.kv_plan = {}
	_FakeModelRegistry.profiles = {"bonsai_2_27b": {"model_path": __file__, "runtime": "llama_cpp_prism"}}
	return rs


class TestBuildCommand:
	def test_uses_server_binary_tier_ctx_and_np1(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		resolved = {
			"profile": _FakeModelRegistry.get_profile("bonsai_2_27b"),
			"runtime": dict(_FakeRuntimeRegistry.runtime),
			"server_binary": "/fake/prism/llama-server",
			"model_path": "/fake/model.gguf",
		}
		cmd = srv._build_command(resolved)
		assert cmd[0] == "/fake/prism/llama-server"
		assert "-np" in cmd and cmd[cmd.index("-np") + 1] == "1"
		assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "24576"
		assert cmd[cmd.index("-ngl") + 1] == "-1"
		assert "9999" in cmd

	def test_kv_type_adds_cache_flags(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999, kv_type="q8_0")
		resolved = {"profile": {}, "runtime": {}, "server_binary": "/b", "model_path": "/m.gguf"}
		cmd = srv._build_command(resolved)
		assert "-ctk" in cmd and cmd[cmd.index("-ctk") + 1] == "q8_0"
		assert "-ctv" in cmd and cmd[cmd.index("-ctv") + 1] == "q8_0"

	def test_extra_args_appended(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999, extra_args=["--reasoning-budget", "2048"])
		resolved = {"profile": {}, "runtime": {}, "server_binary": "/b", "model_path": "/m.gguf"}
		cmd = srv._build_command(resolved)
		assert cmd[-2:] == ["--reasoning-budget", "2048"]


class TestFailClean:
	def test_unknown_profile_raises(self, mod):
		srv = mod.RuntimeServer("nope")
		with pytest.raises(mod.RuntimeServerError, match="no existe"):
			srv._resolve()

	def test_missing_runtime_raises_unavailable(self, mod):
		_FakeRuntimeRegistry.fail = True
		srv = mod.RuntimeServer("bonsai_2_27b")
		from red_pill.core.runtime_registry import RuntimeUnavailableError

		with pytest.raises(RuntimeUnavailableError):
			srv._resolve()

	def test_missing_model_file_raises(self, mod, tmp_path):
		server = tmp_path / "fake-llama-server"
		server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		os.chmod(server, 0o755)
		_FakeRuntimeRegistry.runtime = {"id": "llama_cpp_prism", "server": str(server), "binary": str(server)}
		_FakeModelRegistry.profiles = {"x": {"model_path": "/definitely/not/here.gguf", "runtime": "llama_cpp_prism"}}
		srv = mod.RuntimeServer("x")
		with pytest.raises(mod.RuntimeServerError, match="model_path inexistente"):
			srv._resolve()


class TestLifecycle:
	def test_wait_ready_detects_dead_process(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		srv._proc = _FakeProc(poll_sequence=[1])
		with pytest.raises(mod.RuntimeServerError, match="murió durante el arranque"):
			srv.wait_ready(timeout=1)

	def test_stop_terminates(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		proc = _FakeProc()
		srv._proc = proc
		srv.stop()
		assert proc.terminated and proc.waited
		assert srv._proc is None

	def test_chat_requires_running(self, mod):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		with pytest.raises(mod.RuntimeServerError, match="no está corriendo"):
			srv.chat([{"role": "user", "content": "hola"}])


class TestVramGate:
	def test_raises_when_vram_insufficient_and_no_swap(self, mod):
		from unittest.mock import patch

		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		with patch("red_pill.core.vram_probe.VramProbe.get_free_mb", return_value=500):
			with pytest.raises(mod.RuntimeServerError, match="VRAM insuficiente"):
				srv._ensure_vram(__file__)

	def test_swap_unloads_daemon_and_continues(self, mod, monkeypatch):
		from unittest.mock import patch

		called = []
		monkeypatch.setattr(mod.RuntimeServer, "_request_daemon_unload", lambda self: called.append(1) or True)
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999, unload_daemon=True)
		with patch("red_pill.core.vram_probe.VramProbe.get_free_mb", side_effect=[500, 8000]):
			srv._ensure_vram(__file__)
		assert called == [1]

	def test_unload_not_called_when_vram_fits(self, mod, monkeypatch):
		from unittest.mock import patch

		called = []
		monkeypatch.setattr(mod.RuntimeServer, "_request_daemon_unload", lambda self: called.append(1) or True)
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999, unload_daemon=True)
		with patch("red_pill.core.vram_probe.VramProbe.get_free_mb", return_value=8000):
			srv._ensure_vram(__file__)
		assert called == []

	def test_request_daemon_unload_false_on_network_error(self, mod, monkeypatch):
		def boom(req, timeout=None):
			raise OSError("connection refused")

		monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		assert srv._request_daemon_unload() is False


class TestKvPlanIntegration:
	def _fake_binary(self, tmp_path):
		import os as _os

		server = tmp_path / "fake-llama-server"
		server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		_os.chmod(server, 0o755)
		_FakeRuntimeRegistry.runtime = {"id": "llama_cpp_prism", "server": str(server), "binary": str(server)}

	def test_start_applies_kv_plan(self, mod, monkeypatch, tmp_path):
		from unittest.mock import patch

		self._fake_binary(tmp_path)
		_FakeModelRegistry.kv_plan = {
			"kv_type": "q8_0",
			"ctx": 24576,
			"required_mb": 6682,
			"free_mb": 7000,
			"fits": True,
			"degraded": True,
		}
		monkeypatch.setattr(mod, "get_data_dir", lambda: tmp_path)
		monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
		monkeypatch.setattr(mod.RuntimeServer, "wait_ready", lambda self, timeout=None: None)
		with patch("red_pill.core.vram_probe.VramProbe.get_free_mb", return_value=8000):
			srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
			srv.start()
		assert srv.kv_type == "q8_0"
		assert srv.ctx == 24576

	def test_start_raises_when_no_kv_fits(self, mod, monkeypatch, tmp_path):
		self._fake_binary(tmp_path)
		_FakeModelRegistry.kv_plan = {"kv_type": None, "ctx": 65536, "free_mb": 5000, "fits": False, "degraded": False}
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		with pytest.raises(mod.RuntimeServerError, match="ningún KV cabe"):
			srv.start()


class TestStateRegistry:
	def test_running_servers_filters_stale(self, mod, monkeypatch, tmp_path):
		monkeypatch.setattr(mod, "get_data_dir", lambda: tmp_path)
		state_dir = tmp_path / "runtime_servers"
		state_dir.mkdir(parents=True, exist_ok=True)
		(state_dir / "alive.json").write_text(json.dumps({"profile": "alive", "pid": os.getpid()}), encoding="utf-8")
		dead = state_dir / "dead.json"
		dead.write_text(json.dumps({"profile": "dead", "pid": 999999}), encoding="utf-8")

		running = mod.running_servers()
		assert [s["profile"] for s in running] == ["alive"]
		assert not dead.exists()  # huérfano limpiado

	def test_stop_dedicated_servers_kills_real_process(self, mod, monkeypatch, tmp_path):
		import subprocess as sp

		monkeypatch.setattr(mod, "get_data_dir", lambda: tmp_path)
		state_dir = tmp_path / "runtime_servers"
		state_dir.mkdir(parents=True, exist_ok=True)
		proc = sp.Popen(["sleep", "30"])
		try:
			(state_dir / "victima.json").write_text(json.dumps({"profile": "victima", "pid": proc.pid}), encoding="utf-8")
			stopped = mod.stop_dedicated_servers(profile_name="victima")
			assert stopped == 1
			proc.wait(timeout=5)
			assert proc.poll() is not None
			assert not (state_dir / "victima.json").exists()
		finally:
			if proc.poll() is None:
				proc.kill()

	def test_start_writes_state_and_stop_removes(self, mod, monkeypatch, tmp_path):
		from unittest.mock import patch

		server = tmp_path / "fake-llama-server"
		server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		os.chmod(server, 0o755)
		_FakeRuntimeRegistry.runtime = {"id": "llama_cpp_prism", "server": str(server), "binary": str(server)}
		monkeypatch.setattr(mod, "get_data_dir", lambda: tmp_path)
		monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
		monkeypatch.setattr(mod.RuntimeServer, "wait_ready", lambda self, timeout=None: None)
		with patch("red_pill.core.vram_probe.VramProbe.get_free_mb", return_value=8000):
			srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
			srv.start()
			state = tmp_path / "runtime_servers" / "bonsai_2_27b.json"
			assert state.exists()
			srv.stop()
			assert not state.exists()


class _FakeHTTPResponse:
	def __init__(self, payload):
		self._payload = json.dumps(payload).encode("utf-8")
		self.status = 200

	def read(self):
		return self._payload

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		return False


class TestChat:
	def test_chat_posts_to_openai_endpoint_and_parses(self, mod, monkeypatch):
		srv = mod.RuntimeServer("bonsai_2_27b", port=9999)
		srv._proc = _FakeProc()
		captured = {}

		def fake_urlopen(req, timeout=None):
			captured["url"] = req.full_url
			captured["body"] = json.loads(req.data.decode("utf-8"))
			return _FakeHTTPResponse({"choices": [{"message": {"content": "hola"}}]})

		monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
		resp = srv.chat(
			[{"role": "user", "content": "hola"}],
			max_tokens=128,
			temperature=1.0,
			chat_template_kwargs={"reasoning_effort": "medium"},
		)
		assert captured["url"] == "http://127.0.0.1:9999/v1/chat/completions"
		assert captured["body"]["max_tokens"] == 128
		assert captured["body"]["chat_template_kwargs"] == {"reasoning_effort": "medium"}
		assert resp["choices"][0]["message"]["content"] == "hola"
