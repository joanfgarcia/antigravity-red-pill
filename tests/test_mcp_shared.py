"""AD-018: MCP compartido (backend UDS + proxy stdio).

Los tests unitarios cubren la identidad del proxy. El E2E real (backend + dos
proxies + dos sesiones) está gateado: arranca un proceso pesado y usa config
real; se activa con `REDPILL_MCP_SHARED_E2E=1`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from red_pill.mcp_proxy import default_socket, identity_payload

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_identity_payload_from_env(monkeypatch):
	for key in ("REDPILL_ORIGINATOR", "REDPILL_WORKSPACE", "REDPILL_CONTINUITY_ID", "REDPILL_MISSION_ID", "REDPILL_ROLE"):
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv("REDPILL_HARNESS", "opencode")
	monkeypatch.setenv("REDPILL_ORIGINATOR", "opencode:s1")
	monkeypatch.setenv("REDPILL_WORKSPACE", "/ws/proj")
	monkeypatch.setenv("REDPILL_CONTINUITY_ID", "alma-1")
	monkeypatch.setenv("REDPILL_MISSION_ID", "repo:x")
	payload = identity_payload()
	assert payload["originator"] == "opencode:s1"
	assert payload["workdir"] == "/ws/proj"
	assert payload["continuity_id"] == "alma-1"
	assert payload["mission_id"] == "repo:x"
	assert payload["harness"] == "opencode"


def test_identity_payload_reads_opencode_bridge(tmp_path, monkeypatch):
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
	monkeypatch.setenv("REDPILL_HARNESS", "opencode")
	monkeypatch.delenv("REDPILL_ORIGINATOR", raising=False)
	monkeypatch.delenv("REDPILL_WORKSPACE", raising=False)
	state = tmp_path / "red-pill" / "state"
	state.mkdir(parents=True)
	(state / "opencode_session.json").write_text(
		json.dumps({"provider": "opencode", "session_id": "ses_abc", "workdir": "/ws/oc"}),
		encoding="utf-8",
	)
	payload = identity_payload("opencode")
	assert payload["originator"] == "opencode:ses_abc"
	assert payload["workdir"] == "/ws/oc"


def test_default_socket_prefers_runtime(monkeypatch):
	monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
	assert default_socket() == "/run/user/1000/red-pill/mcp.sock"


def _env(base: Path) -> dict:
	return {
		**os.environ,
		"XDG_DATA_HOME": str(base / "data"),
		"XDG_STATE_HOME": str(base / "state"),
		"XDG_CACHE_HOME": str(base / "cache"),
		"PYTHONPATH": str(REPO_ROOT / "src"),
	}


async def _session(sock: str, label: str, base: Path) -> str:
	from mcp import StdioServerParameters
	from mcp.client.session import ClientSession
	from mcp.client.stdio import stdio_client

	env = {
		**_env(base),
		"REDPILL_HARNESS": "opencode",
		"REDPILL_ORIGINATOR": f"opencode:e2e-{label}",
		"REDPILL_CONTINUITY_ID": f"alma-e2e-{label}",
		"REDPILL_MISSION_ID": "repo:e2e",
	}
	params = StdioServerParameters(
		command=sys.executable,
		args=["-m", "red_pill.mcp_proxy", "--socket", sock, "--harness", "opencode"],
		env=env,
		cwd=str(REPO_ROOT),
	)
	async with stdio_client(params) as (read, write):
		async with ClientSession(read, write) as session:
			await session.initialize()
			result = await session.call_tool("sovereign_handshake", {"user_prompt": "e2e", "mode": "low"})
			text = "\n".join(getattr(c, "text", "") for c in result.content)
			match = re.findall(r"<session[^>]*/>", text)
			return match[0] if match else text[:200]


@pytest.mark.integration
@pytest.mark.timeout(180)
@pytest.mark.skipif(os.getenv("REDPILL_MCP_SHARED_E2E") != "1", reason="E2E MCP compartido desactivado")
def test_shared_backend_two_sessions(tmp_path):
	sock = str(tmp_path / "mcp.sock")
	env = _env(tmp_path)
	backend = subprocess.Popen(
		[sys.executable, "-m", "red_pill.mcp_backend", "--socket", sock],
		env=env,
		cwd=str(REPO_ROOT),
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)
	try:
		for _ in range(150):
			if os.path.exists(sock):
				break
			if backend.poll() is not None:
				pytest.fail("el backend MCP compartido murió al arrancar")
			time.sleep(0.2)
		else:
			pytest.fail("timeout esperando el socket del backend")
		results = asyncio.run(_run_both(sock, tmp_path))
	finally:
		backend.terminate()
		try:
			backend.wait(timeout=10)
		except subprocess.TimeoutExpired:
			backend.kill()
	assert 'continuity_id="alma-e2e-a"' in results["a"]
	assert 'continuity_id="alma-e2e-b"' in results["b"]
	assert 'leg="opencode:e2e-a"' in results["a"]
	assert 'leg="opencode:e2e-b"' in results["b"]


async def _run_both(sock: str, base: Path) -> dict:
	a, b = await asyncio.gather(_session(sock, "a", base), _session(sock, "b", base))
	return {"a": a, "b": b}
