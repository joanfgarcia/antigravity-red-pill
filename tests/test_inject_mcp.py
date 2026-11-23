"""inject_mcp: el servidor RedPill-Kernel recibe `env.REDPILL_HARNESS` por
destino (Alma y Coro A1/A2 — cada IDE debe conocer su arnés para no confundir el
bridge de sesión entre servidores MCP que comparten STATE_DIR)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import inject_mcp  # noqa: E402


def test_harness_for_targets():
	assert inject_mcp._harness_for("/home/u/.gemini/config/mcp_config.json") == "antigravity"
	assert inject_mcp._harness_for("/home/u/.gemini/antigravity/mcp_config.json") == "antigravity"
	assert inject_mcp._harness_for("/ws/.mcp.json") == "claude_code"
	assert inject_mcp._harness_for("/home/u/.claude.json") == "claude_code"
	assert inject_mcp._harness_for("/home/u/.config/Claude/claude_desktop_config.json") == "claude_code"
	assert inject_mcp._harness_for("/home/u/.config/opencode/opencode.jsonc") is None
	# Cline (saoudrizwan.claude-dev) NO es Claude Code: no debe heredar su bridge.
	cline = "/home/u/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
	assert inject_mcp._harness_for(cline) is None


def test_with_harness_injects_env_without_mutating_source():
	defn = {"command": "uv", "args": ["--directory", "/rp", "run", "python", "x.py"]}
	out = inject_mcp._with_harness(defn, "/ws/.mcp.json")
	assert out["env"] == {"REDPILL_HARNESS": "claude_code"}
	assert out["command"] == "uv"
	assert "env" not in defn  # el def original no se muta (se comparte entre destinos)


def test_inject_writes_harness_env(tmp_path):
	target = tmp_path / ".mcp.json"
	servers = {"RedPill-Kernel": {"command": "uv", "args": ["run", "python", "x.py"]}}
	changed = inject_mcp.inject(str(target), servers, assert_names={"RedPill-Kernel"})
	assert changed
	data = json.loads(target.read_text(encoding="utf-8"))
	assert data["mcpServers"]["RedPill-Kernel"]["env"] == {"REDPILL_HARNESS": "claude_code"}


def test_inject_gemini_target_is_antigravity(tmp_path):
	target = tmp_path / ".gemini" / "config" / "mcp_config.json"
	servers = {"RedPill-Kernel": {"command": "uv", "args": ["run"]}}
	inject_mcp.inject(str(target), servers, assert_names={"RedPill-Kernel"})
	data = json.loads(target.read_text(encoding="utf-8"))
	assert data["mcpServers"]["RedPill-Kernel"]["env"] == {"REDPILL_HARNESS": "antigravity"}


# ── Claude por el proxy del backend compartido (AD-018) ──────────────────────


def _vars(tmp_path, shared="true", sock=True):
	python = tmp_path / "python"
	python.write_text("#", encoding="utf-8")
	socket_path = tmp_path / "mcp.sock"
	if sock:
		socket_path.write_text("", encoding="utf-8")
	return {"MCP_SHARED": shared, "PYTHON": str(python), "MCP_SOCKET": str(socket_path), "REDPILL_DIR": "/rp"}


def test_backend_compartido_disponible(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))  # sin unit de systemd
	assert inject_mcp.shared_backend_available(_vars(tmp_path))
	assert not inject_mcp.shared_backend_available(_vars(tmp_path, shared="false"))
	bare = tmp_path / "bare"
	bare.mkdir()
	assert not inject_mcp.shared_backend_available(_vars(bare, sock=False))
	assert not inject_mcp.shared_backend_available({**_vars(tmp_path), "PYTHON": str(tmp_path / "nope")})


def test_solo_claude_va_por_el_proxy(tmp_path):
	direct = {"RedPill-Kernel": {"command": "uv", "args": ["run"]}, "otro": {"command": "x"}}
	proxy = inject_mcp.redpill_proxy_server(_vars(tmp_path))
	assert proxy["args"][:2] == ["-m", "red_pill.mcp_proxy"]
	assert proxy["args"][-2:] == ["--harness", "claude_code"]
	assert proxy["env"]["PYTHONPATH"] == "/rp/src"
	for target in ("/h/.claude.json", "/h/.config/Claude/claude_desktop_config.json", "/ws/.mcp.json"):
		out = inject_mcp.servers_for(target, direct, proxy)
		assert out["RedPill-Kernel"] is proxy
		assert out["otro"] is direct["otro"]
	for target in ("/h/.gemini/config/mcp_config.json", "/h/x/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"):
		assert inject_mcp.servers_for(target, direct, proxy) is direct
	assert inject_mcp.servers_for("/h/.claude.json", direct, None) is direct


def test_proxy_escrito_lleva_el_arnes(tmp_path):
	target = tmp_path / ".claude.json"
	proxy = inject_mcp.redpill_proxy_server(_vars(tmp_path))
	inject_mcp.inject(str(target), {"RedPill-Kernel": proxy}, assert_names={"RedPill-Kernel"})
	entry = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["RedPill-Kernel"]
	assert entry["env"] == {"PYTHONPATH": "/rp/src", "REDPILL_HARNESS": "claude_code"}
