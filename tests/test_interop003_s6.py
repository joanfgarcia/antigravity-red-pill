"""RFC-INTEROP-003 S6 — env de identidad a arneses externos."""

from __future__ import annotations

import json
from types import SimpleNamespace

from red_pill.swarm.bridges.claude import ClaudeBridge
from red_pill.swarm.bridges.identity_env import identity_env
from red_pill.swarm.bridges.opencode import OpenCodeBridge
from red_pill.swarm.bridges.pi import PiBridge

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"
IDENTITY = {
	"continuity_id": CID,
	"mission_id": "forge:x",
	"parent_mission_id": "repo:next",
	"originator": "dag:job-1/stage-a",
	"role": "job",
	"job_id": "job-1",
}


def test_identity_env_uses_parent_mission_for_soul():
	env = identity_env(**IDENTITY)
	assert env["REDPILL_CONTINUITY_ID"] == CID
	assert env["REDPILL_MISSION_ID"] == "repo:next"
	assert env["REDPILL_PARENT_MISSION_ID"] == "repo:next"
	assert env["REDPILL_ORIGINATOR"] == "dag:job-1/stage-a"
	assert env["REDPILL_JOB_ID"] == "job-1"
	assert identity_env() == {}


def test_claude_bridge_exports_identity(monkeypatch):
	seen = {}

	def fake_run(cmd, **kwargs):
		seen.update(kwargs)
		return SimpleNamespace(returncode=0, stdout=json.dumps({"session_id": "s1", "result": "ok"}), stderr="")

	monkeypatch.setattr("red_pill.swarm.bridges.claude.subprocess.run", fake_run)
	bridge = ClaudeBridge(claude_path="/bin/true", **IDENTITY)
	out = bridge.prompt("hola", model="flash")
	assert out.ok and out.response == "ok"
	assert seen["env"]["REDPILL_CONTINUITY_ID"] == CID
	assert seen["env"]["REDPILL_MISSION_ID"] == "repo:next"
	assert seen["env"]["REDPILL_ORIGINATOR"] == "dag:job-1/stage-a"


def test_pi_bridge_exports_identity(monkeypatch):
	seen = {}
	stdout = "\n".join(
		[
			json.dumps({"type": "session", "id": "s2"}),
			json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}),
		]
	)

	def fake_run(cmd, **kwargs):
		seen.update(kwargs)
		return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

	monkeypatch.setattr("red_pill.swarm.bridges.pi.subprocess.run", fake_run)
	bridge = PiBridge(pi_path="/bin/true", **IDENTITY)
	out = bridge.prompt("hola", model="flash")
	assert out.ok and out.response == "ok"
	assert seen["env"]["REDPILL_CONTINUITY_ID"] == CID
	assert seen["env"]["REDPILL_PARENT_MISSION_ID"] == "repo:next"


def test_opencode_bridge_exports_identity(monkeypatch):
	seen = {}

	def fake_run(cmd, **kwargs):
		seen.update(kwargs)
		return SimpleNamespace(
			returncode=0,
			stdout='{"type":"step_start","sessionID":"s3"}\n{"type":"text","part":{"text":"ok"}}\n',
			stderr="",
		)

	monkeypatch.setattr("red_pill.swarm.bridges.opencode.subprocess.run", fake_run)
	bridge = OpenCodeBridge(opencode_path="/bin/true", **IDENTITY)
	bridge._cli_major_cache = 1
	bridge._scribe_plugin = True
	out = bridge.prompt("hola", model="flash")
	assert out.ok and out.response == "ok"
	assert seen["env"]["REDPILL_CONTINUITY_ID"] == CID
	assert seen["env"]["REDPILL_JOB_ID"] == "job-1"


def test_agentic_driver_passes_identity_to_external_bridge(monkeypatch):
	import red_pill.swarm.bridges.factory as factory_mod
	from red_pill.jobs.drivers.agentic import AgenticJobDriver

	seen = {}

	class FakeBridge:
		pass

	def fake_create(backend, **kwargs):
		seen["backend"] = backend
		seen.update(kwargs)
		return FakeBridge()

	monkeypatch.setattr(factory_mod, "create_bridge", fake_create)
	driver = AgenticJobDriver()
	driver.job_id = "job-9"
	driver._create_bridge({**IDENTITY, "backend": "opencode", "mission_id": "forge:x"})
	assert seen["continuity_id"] == CID
	assert seen["parent_mission_id"] == "repo:next"
	assert seen["job_id"] == "job-9"
	assert seen["originator"] == "dag:job-1/stage-a"


def test_agent_minion_exports_identity_for_external_backend(monkeypatch):
	import asyncio

	import red_pill.swarm.bridges as bridges_mod
	from red_pill.swarm.agents.agent import AgentMinion

	seen = {}

	class FakeBridge:
		def prompt(self, text, **kwargs):
			seen["identity"] = {
				k: getattr(self, k, None)
				for k in ("continuity_id", "mission_id", "parent_mission_id", "originator", "role", "job_id")
			}
			return SimpleNamespace(ok=True, response="ok", conversation_id="s", error=None)

	def fake_create(backend, **kwargs):
		for key, value in kwargs.items():
			seen[key] = value
		return FakeBridge()

	monkeypatch.setattr(bridges_mod, "create_bridge", fake_create)
	result = asyncio.run(AgentMinion().execute("hola", backend="claude", **IDENTITY))
	assert result["status"] == "success"
	assert seen["continuity_id"] == CID
	assert seen["parent_mission_id"] == "repo:next"
	assert seen["job_id"] == "job-1"


def test_cascade_propagates_identity(monkeypatch):
	import red_pill.swarm.bridges.factory as factory_mod
	from red_pill.config import BridgeTarget
	from red_pill.swarm.bridges.cascade import CascadeBridge

	seen = {}

	class FakeBridge:
		def prompt(self, *args, **kwargs):
			return SimpleNamespace(ok=True, response="ok", conversation_id="s", error=None)

	def fake_create(backend, **kwargs):
		seen.update(kwargs)
		return FakeBridge()

	monkeypatch.setattr(factory_mod, "create_bridge", fake_create)
	cascade = CascadeBridge([BridgeTarget(backend="claude", model="x")], **IDENTITY)
	cascade._build("claude")
	assert seen["continuity_id"] == CID
	assert seen["originator"] == "dag:job-1/stage-a"
