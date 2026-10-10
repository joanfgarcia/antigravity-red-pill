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
