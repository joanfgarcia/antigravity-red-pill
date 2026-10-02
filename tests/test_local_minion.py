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
	assert res["used_tools"] is True and res["tool_calls"] == 1
	# the tool result is fed back as a USER turn (the handler drops role="tool")
	assert any(m.get("role") == "user" and "Tool `run_bash` result" in str(m.get("content")) for m in res["messages"])


async def test_native_text_toolcall_is_parsed(monkeypatch):
	# Granite 4.2 native template: the tool call arrives as TEXT, not tool_calls.
	native = (
		"<think>leo el fichero</think>\n"
		"<tool_call>\n<function=run_bash>\n<parameter=command>\ncat manifest.txt\n"
		"</parameter>\n</function>\n</tool_call>"
	)
	provider = FakeProvider(
		[
			{"role": "assistant", "content": native, "tool_calls": None},
			{"role": "assistant", "content": "", "tool_calls": None},
			{"role": "assistant", "content": "vault-7731"},
		]
	)
	_use_provider(monkeypatch, provider)
	_fake_shell(monkeypatch, FakeProc(rc=0, out=b"vault-7731\n"))
	res = await local_minion.run_local_minion("lee manifest.txt")
	assert res["ok"] is True and res["used_tools"] is True
	assert res["answer"] == "vault-7731"
	# the parsed call reached run_bash
	assert provider.calls[0].get("tools") is not None


def _native(command):
	return f"<tool_call>\n<function=run_bash>\n<parameter=command>\n{command}\n</parameter>\n</function>\n</tool_call>"


def test_parse_native_toolcalls_granite():
	calls, malformed = local_minion._parse_native_toolcalls(_native("ls -1"))
	assert malformed == 0 and len(calls) == 1
	assert calls[0]["function"]["name"] == "run_bash"
	# arguments stay a MAPPING (the native template renders them via |items)
	assert calls[0]["function"]["arguments"] == {"command": "ls -1"}
	# prose with no tool-call markup → no calls, nothing malformed
	assert local_minion._parse_native_toolcalls("solo una respuesta") == ([], 0)


def test_parse_native_ignora_tool_call_dentro_del_razonamiento():
	# Regresión: un <tool_call> escrito MIENTRAS razona se ejecutaba por run_bash.
	musing = f"<think>podría hacer {_native('rm -rf build')} pero mejor no</think>La respuesta es 42"
	assert local_minion._parse_native_toolcalls(musing) == ([], 0)
	# razonamiento sin cerrar (presupuesto agotado) → tampoco es una llamada
	assert local_minion._parse_native_toolcalls(f"<think>quizá {_native('rm -rf build')}") == ([], 0)
	# la llamada DESPUÉS del razonamiento sí cuenta
	calls, _ = local_minion._parse_native_toolcalls(f"<think>{_native('rm -rf build')}</think>{_native('ls')}")
	assert [c["function"]["arguments"]["command"] for c in calls] == ["ls"]


def test_parse_native_cuenta_los_bloques_malformados():
	truncated = "<tool_call>\n<function=run_bash>\n<parameter=command>\nls -"
	assert local_minion._parse_native_toolcalls(truncated) == ([], 1)
	calls, malformed = local_minion._parse_native_toolcalls(_native("ls") + "\n" + truncated)
	assert len(calls) == 1 and malformed == 1


def test_parse_native_ids_unicos_por_turno():
	text = _native("ls") + _native("pwd")
	ids = [c["id"] for c in local_minion._parse_native_toolcalls(text, turn=0)[0]]
	ids += [c["id"] for c in local_minion._parse_native_toolcalls(text, turn=1)[0]]
	assert len(set(ids)) == 4


async def test_tool_call_en_el_razonamiento_no_se_ejecuta(monkeypatch):
	musing = f"<think>tal vez {_native('rm -rf build')}… no, no hace falta</think>No hay nada que borrar."
	_use_provider(monkeypatch, FakeProvider([{"role": "assistant", "content": musing, "tool_calls": None}]))

	async def _forbidden(cmd, **kwargs):
		raise AssertionError(f"run_bash ejecutado: {cmd}")

	monkeypatch.setattr(asyncio, "create_subprocess_shell", _forbidden)
	res = await local_minion.run_local_minion("¿hay algo que limpiar?")
	assert res["ok"] is True and res["tool_calls"] == 0
	assert res["answer"] == "No hay nada que borrar."


async def test_tool_call_truncado_se_realimenta_como_error(monkeypatch):
	# Regresión: el markup truncado volvía como respuesta final con ok=True.
	truncated = "<think>leo</think><tool_call>\n<function=run_bash>\n<parameter=command>\ncat manif"
	provider = FakeProvider(
		[
			{"role": "assistant", "content": truncated, "tool_calls": None},
			{"role": "assistant", "content": _native("cat manifest.txt"), "tool_calls": None},
			{"role": "assistant", "content": "vault-7731"},
		]
	)
	_use_provider(monkeypatch, provider)
	_fake_shell(monkeypatch, FakeProc(rc=0, out=b"vault-7731\n"))
	res = await local_minion.run_local_minion("lee manifest.txt")
	assert res["ok"] is True and res["answer"] == "vault-7731"
	assert res["tool_calls"] == 1
	assert any("malformed or truncated" in str(m.get("content")) for m in res["messages"] if m.get("role") == "user")


async def test_tool_call_malformado_repetido_abandona(monkeypatch):
	truncated = "<tool_call>\n<function=run_bash>\n<parameter=command>\nls"
	_use_provider(monkeypatch, FakeProvider([{"role": "assistant", "content": truncated} for _ in range(5)]))
	res = await local_minion.run_local_minion("lista")
	assert res["ok"] is False
	assert "consecutive tool errors" in res["answer"]
	assert "<tool_call" not in res["answer"]


async def test_varias_llamadas_nativas_se_ejecutan_todas_en_orden(monkeypatch):
	# Regresión: solo se ejecutaba la primera (re.search) y el resto se perdía.
	provider = FakeProvider(
		[
			{"role": "assistant", "content": _native("ls") + "\n" + _native("pwd"), "tool_calls": None},
			{"role": "assistant", "content": "hecho"},
		]
	)
	_use_provider(monkeypatch, provider)
	ran = []

	async def fake(cmd, **kwargs):
		ran.append(cmd)
		return FakeProc(rc=0, out=b"x\n")

	monkeypatch.setattr(asyncio, "create_subprocess_shell", fake)
	res = await local_minion.run_local_minion("ls y pwd")
	assert res["ok"] is True and ran == ["ls", "pwd"]
	assert res["tool_calls"] == 2


async def test_presupuesto_total_de_tool_calls(monkeypatch):
	# Un solo turno con más llamadas que el presupuesto: se ejecutan MAX_TOOL_CALLS y se corta.
	many = {
		"role": "assistant",
		"content": None,
		"tool_calls": [
			{"id": f"c{i}", "function": {"name": "run_bash", "arguments": '{"command": "true"}'}}
			for i in range(local_minion.MAX_TOOL_CALLS + 3)
		],
	}
	_use_provider(monkeypatch, FakeProvider([many]))
	_fake_shell(monkeypatch, FakeProc(rc=0, out=b""))
	res = await local_minion.run_local_minion("abusa")
	assert res["ok"] is False and "cap" in res["answer"]
	assert res["tool_calls"] == local_minion.MAX_TOOL_CALLS
	assert f"at most {local_minion.MAX_TOOL_CALLS} tool calls" in local_minion.SYSTEM_PROMPT


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
