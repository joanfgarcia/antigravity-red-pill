"""TST-BR-001: RuntimeBattleRunner y factory runtime-aware (RFC-HARNESS-003 corte 3).

Herméticos: sin GPU ni procesos reales — se carga `scripts/model_battle_lib.py`
por ruta (no es paquete) y se inyectan fakes del RuntimeServer / BattleRunner.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
	"model_battle_lib_test",
	Path(__file__).resolve().parent.parent / "scripts" / "model_battle_lib.py",
)
mbl = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = mbl  # @dataclass resuelve cls.__module__ vía sys.modules
_SPEC.loader.exec_module(mbl)


class _FakeServer:
	instances = []

	def __init__(self, model_name, ctx=None, extra_args=None, unload_daemon=True):
		self.profile_name = model_name
		self.kv_type = "f16"
		self.ctx = ctx or 24576
		self.started = False
		self.stopped = False
		self.last_chat = None
		self.raise_on_chat = False
		_FakeServer.instances.append(self)

	def start(self):
		self.started = True
		return self

	def stop(self):
		self.stopped = True

	def chat(self, messages, **kwargs):
		if self.raise_on_chat:
			raise RuntimeError("boom")
		self.last_chat = {"messages": messages, **kwargs}
		return {"choices": [{"message": {"content": "220"}}]}


@pytest.fixture
def fake_server(monkeypatch):
	_FakeServer.instances = []
	monkeypatch.setattr("red_pill.inference.runtime_server.RuntimeServer", _FakeServer)
	return _FakeServer


@pytest.fixture(autouse=True)
def _patch_resolve(monkeypatch):
	"""RuntimeBattleRunner resuelve la conducta vía model_runtime.resolve():
	se inyecta un ResolvedModel fake (hermético, sin config real)."""
	from types import SimpleNamespace

	def _fake_resolve(body=None):
		return SimpleNamespace(
			profile_name=(body or {}).get("model", "fake"),
			resolved_n_ctx=lambda: 24576,
			temperature=1.0,
			sampling={},
			max_tokens=2048,
			thinking="on",
			reasoning_effort=None,
		)

	monkeypatch.setattr("red_pill.core.model_runtime.resolve", _fake_resolve)


def _probe():
	return mbl.Probe(
		name="math",
		system_prompt="sys",
		user_message="user",
		validator=lambda raw: {"valid": "220" in raw},
		max_tokens=128,
		temperature=0.2,
	)


class TestRuntimeBattleRunner:
	def test_runs_probe_through_dedicated_server(self, fake_server):
		runner = mbl.RuntimeBattleRunner("bonsai_2_27b", n_ctx=24576)
		res = runner.run(_probe())
		srv = fake_server.instances[-1]
		assert srv.started
		assert srv.last_chat["messages"][0] == {"role": "system", "content": "sys"}
		assert srv.last_chat["messages"][1] == {"role": "user", "content": "user"}
		assert srv.last_chat["max_tokens"] == 128
		assert srv.last_chat["temperature"] == 0.2
		assert res.validation["valid"] is True
		assert res.model == "bonsai_2_27b"
		runner.close()
		assert srv.stopped

	def test_error_becomes_invalid_output_not_crash(self, fake_server):
		runner = mbl.RuntimeBattleRunner("bonsai_2_27b")
		fake_server.instances[-1].raise_on_chat = True
		res = runner.run(_probe())
		assert res.raw_output.startswith("<<error")

	def test_run_all_shares_one_server(self, fake_server):
		runner = mbl.RuntimeBattleRunner("bonsai_2_27b")
		runner.run_all([_probe(), _probe()])
		assert len(fake_server.instances) == 1
		assert len(runner.results) == 2


class TestRunnerForFactory:
	def _patch_registries(self, monkeypatch, profile, default="llama_cpp_stock"):
		from red_pill.core.model_registry import ModelRegistry
		from red_pill.core.runtime_registry import RuntimeRegistry

		monkeypatch.setattr(ModelRegistry, "get_profile", lambda name: dict(profile))
		monkeypatch.setattr(RuntimeRegistry, "default_id", classmethod(lambda cls: default))

	def test_declared_runtime_uses_dedicated_runner(self, monkeypatch):
		self._patch_registries(monkeypatch, {"runtime": "llama_cpp_prism", "model_path": "/x.gguf"})
		created = []

		class _Rec:
			def __init__(self, name, n_ctx=None, extra_args=None):
				created.append(name)

		monkeypatch.setattr(mbl, "RuntimeBattleRunner", _Rec)
		runner = mbl.runner_for("bonsai_2_27b", n_ctx=24576)
		assert isinstance(runner, _Rec)
		assert created == ["bonsai_2_27b"]

	def test_stock_profile_uses_classic_runner(self, monkeypatch):
		self._patch_registries(monkeypatch, {"model_path": "/granite.gguf"})
		created = []

		class _Rec:
			def __init__(self, name, path, **kwargs):
				created.append((name, path))

		monkeypatch.setattr(mbl, "BattleRunner", _Rec)
		runner = mbl.runner_for("granite_4_2_8b")
		assert isinstance(runner, _Rec)
		assert created == [("granite_4_2_8b", "/granite.gguf")]

	def test_fastflowlm_runtime_uses_flm_runner(self, monkeypatch):
		from red_pill.core.runtime_registry import RuntimeRegistry

		self._patch_registries(monkeypatch, {"runtime": "fastflowlm", "model_tag": "gpt-oss:20b"})
		monkeypatch.setattr(RuntimeRegistry, "get", lambda rid, variant=None: {"id": rid, "kind": "fastflowlm"})
		created = []

		class _Rec:
			def __init__(self, name):
				created.append(name)

		monkeypatch.setattr(mbl, "FastFlowLMRunner", _Rec)
		runner = mbl.runner_for("npu_gpt_oss_20b")
		assert isinstance(runner, _Rec)
		assert created == ["npu_gpt_oss_20b"]

	def test_stock_profile_without_path_raises(self, monkeypatch):
		self._patch_registries(monkeypatch, {})
		with pytest.raises(ValueError, match="sin gguf_path"):
			mbl.runner_for("misterioso")


class TestFastFlowLMRunnerArgs:
	def _bare(self):
		runner = mbl.FastFlowLMRunner.__new__(mbl.FastFlowLMRunner)
		runner.model_tag = "gpt-oss:20b"
		runner._serve_args = ["--ctx-len", "16384"]
		runner._request_params = {"reasoning_effort": "low"}
		return runner

	def test_serve_argv_incluye_serve_args(self):
		assert self._bare()._serve_argv() == ["flm", "serve", "gpt-oss:20b", "--ctx-len", "16384"]

	def test_request_body_mergea_request_params(self):
		body = self._bare()._request_body(_probe())
		assert body["reasoning_effort"] == "low"
		assert body["max_tokens"] == 128
		assert body["messages"][1] == {"role": "user", "content": "user"}
