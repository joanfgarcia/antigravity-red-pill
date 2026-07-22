"""Unit tests for the in-house local tool-using minion (mocked — no model/daemon)."""

import asyncio

import red_pill.core.providers as providers_mod
from red_pill.swarm.agents import local_minion


class FakeProvider:
	"""Returns a scripted assistant message per chat() call; records the calls."""

	def __init__(self, script):
		self._script = list(script)
		self.calls = []

	def chat(self, messages, **kwargs):
		self.calls.append(kwargs)
		return self._script.pop(0)


def _use_provider(monkeypatch, provider):
	monkeypatch.setattr(providers_mod.ProviderRegistry, "get_inference_provider", lambda name=None: provider)


def _tool_call(name, arguments):
	return {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": arguments}}]}


class FakeProc:
	def __init__(self, rc=0, out=b"51\n", err=b""):
		self.returncode = rc
		self._out = out
		self._err = err

	async def communicate(self):
		return (self._out, self._err)

	def kill(self):
		pass


def _fake_shell(monkeypatch, proc=None):
	async def fake(cmd, **kwargs):
		return proc or FakeProc()

	monkeypatch.setattr(asyncio, "create_subprocess_shell", fake)


async def test_direct_answer_no_tools(monkeypatch):
	_use_provider(monkeypatch, FakeProvider([{"role": "assistant", "content": "the answer is 4"}]))
	res = await local_minion.run_local_minion("2+2?")
	assert res["ok"] is True
	assert res["answer"] == "the answer is 4"
	assert res["steps"] == 0


async def test_bash_then_finalize(monkeypatch):
	# step0: call run_bash → step1: empty content (handler quirk) → finalize returns "51"
	provider = FakeProvider(
		[
			_tool_call("run_bash", '{"command": "ls -1 /home/joan/tmp | wc -l"}'),
			{"role": "assistant", "content": "", "tool_calls": None},
			{"role": "assistant", "content": "51"},
		]
	)
	_use_provider(monkeypatch, provider)
	_fake_shell(monkeypatch, FakeProc(rc=0, out=b"51\n"))
	res = await local_minion.run_local_minion("count entries", cwd="/home/joan/tmp")
	assert res["ok"] is True
	assert res["answer"] == "51"
	# last chat() call is the finalize pass → no tools forwarded
	assert provider.calls[-1].get("tools") is None
	assert sum(1 for m in res["messages"] if m.get("role") == "tool") == 1


async def test_mcp_tool_dispatch(monkeypatch):
	provider = FakeProvider(
		[
			_tool_call("bunker_memory_api", '{"action": "list_workspace_memory", "payload": {}}'),
			{"role": "assistant", "content": "done"},
		]
	)
	_use_provider(monkeypatch, provider)

	seen = {}

	async def fake_execute(name, payload):
		seen["name"] = name
		seen["payload"] = payload
		return {"result": "ok"}

	import red_pill.registry as reg_mod

	monkeypatch.setattr(reg_mod.registry, "execute", fake_execute)

	res = await local_minion.run_local_minion("look it up")
	assert res["ok"] is True
	assert res["answer"] == "done"
	assert seen["name"] == "bunker_memory_api"
	assert seen["payload"]["action"] == "list_workspace_memory"


async def test_unknown_tool_is_error(monkeypatch):
	out = await local_minion._dispatch("no_such_tool", {}, None)
	assert out.startswith("ERROR: unknown tool")


async def test_consecutive_errors_give_up(monkeypatch):
	# every step calls an unknown tool → ERROR each time → give up at 3
	provider = FakeProvider([_tool_call("no_such_tool", "{}") for _ in range(5)])
	_use_provider(monkeypatch, provider)
	res = await local_minion.run_local_minion("break it")
	assert res["ok"] is False
	assert "consecutive tool errors" in res["answer"]


async def test_hits_tool_call_cap(monkeypatch):
	# always returns a (successful) tool call → never finishes → hits the cap
	provider = FakeProvider([_tool_call("run_bash", '{"command": "true"}') for _ in range(local_minion.MAX_TOOL_ITERS + 2)])
	_use_provider(monkeypatch, provider)
	_fake_shell(monkeypatch, FakeProc(rc=0, out=b""))
	res = await local_minion.run_local_minion("loop forever")
	assert res["ok"] is False
	assert "cap" in res["answer"]
	assert res["steps"] == local_minion.MAX_TOOL_ITERS


async def test_bash_timeout(monkeypatch):
	async def slow_communicate(self):
		await asyncio.sleep(5)
		return (b"", b"")

	monkeypatch.setattr(FakeProc, "communicate", slow_communicate)
	_fake_shell(monkeypatch, FakeProc())
	monkeypatch.setattr(local_minion, "BASH_TIMEOUT", 0.01)
	out = await local_minion._dispatch("run_bash", {"command": "sleep 5"}, None)
	assert out.startswith("ERROR") and "timed out" in out
