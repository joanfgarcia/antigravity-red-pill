"""Unit tests for LocalToolBridge + factory routing (mocked — no model/daemon).

These are SYNC test functions on purpose: LocalToolBridge.prompt() runs its own
event loop via asyncio.run(), so it must be called off any running loop.
"""

import red_pill.swarm.agents.local_minion as lm
from red_pill.swarm.bridges import create_bridge
from red_pill.swarm.bridges.base import BackendType
from red_pill.swarm.bridges.local import LocalBridge, LocalToolBridge


def test_capabilities_report_tools():
	caps = LocalToolBridge().get_capabilities()
	assert caps.mcp_tools is True
	assert caps.backend == BackendType.LOCAL


def test_factory_routes_local_tools():
	assert isinstance(create_bridge("local-tools"), LocalToolBridge)
	assert isinstance(create_bridge("local_tools"), LocalToolBridge)
	assert isinstance(create_bridge("local"), LocalBridge)


def test_prompt_success(monkeypatch):
	async def fake_run(task, *, cwd=None, provider_name="sip"):
		return {"ok": True, "answer": "42", "steps": 1, "messages": []}

	monkeypatch.setattr(lm, "run_local_minion", fake_run)
	res = LocalToolBridge().prompt("what is the answer?", cwd="/tmp", timeout=30)
	assert res.ok is True
	assert res.response == "42"


def test_prompt_failure_sets_error(monkeypatch):
	async def fake_run(task, **kwargs):
		return {"ok": False, "answer": "mala tarde: hit the tool-call cap", "steps": 8, "messages": []}

	monkeypatch.setattr(lm, "run_local_minion", fake_run)
	res = LocalToolBridge().prompt("loop")
	assert res.ok is False
	assert "mala tarde" in (res.error or "")


def test_prompt_exception_sets_error(monkeypatch):
	async def fake_run(task, **kwargs):
		raise RuntimeError("boom")

	monkeypatch.setattr(lm, "run_local_minion", fake_run)
	res = LocalToolBridge().prompt("explode")
	assert res.ok is False
	assert "boom" in (res.error or "")


def test_continue_conversation_delegates(monkeypatch):
	async def fake_run(task, **kwargs):
		return {"ok": True, "answer": "ok", "steps": 0, "messages": []}

	monkeypatch.setattr(lm, "run_local_minion", fake_run)
	res = LocalToolBridge().continue_conversation("again", conversation_id="x")
	assert res.ok is True
	assert res.response == "ok"


def test_health_check(monkeypatch):
	import red_pill.core.providers as providers_mod

	monkeypatch.setattr(providers_mod.ProviderRegistry, "get_inference_provider", lambda name=None: object())
	assert LocalToolBridge().health_check() is True

	def _raise(name=None):
		raise RuntimeError("no provider")

	monkeypatch.setattr(providers_mod.ProviderRegistry, "get_inference_provider", _raise)
	assert LocalToolBridge().health_check() is False
