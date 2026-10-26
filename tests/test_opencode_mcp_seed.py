"""Seed de opencode: proxy compartido por defecto y directo como fallback."""
from __future__ import annotations

import json
from pathlib import Path
from string import Template

SEED = Path(__file__).resolve().parents[1] / "seeds" / "opencode" / "settings" / "opencode.jsonc"
BASE = {
	"UV": "/usr/bin/uv",
	"REDPILL_DIR": "/repo",
	"PYTHON": "/repo/.venv/bin/python",
	"MCP_SOCKET": "/state/mcp.sock",
	"AGENT_CORE_DIR": "/desk",
	"HOME": "/home/op",
}


def _render(**overrides) -> dict:
	values = {**BASE, "MCP_SHARED": "true", "MCP_DIRECT": "false", **overrides}
	return json.loads(Template(SEED.read_text(encoding="utf-8")).safe_substitute(**values))


def test_seed_usa_proxy_por_defecto_y_deja_directo_desactivado():
	cfg = _render()
	mcp = cfg["mcp"]
	assert mcp["RedPill-Kernel"]["enabled"] is True
	assert mcp["RedPill-Kernel"]["command"] == [
		"/repo/.venv/bin/python",
		"-m",
		"red_pill.mcp_proxy",
		"--socket",
		"/state/mcp.sock",
		"--harness",
		"opencode",
	]
	assert mcp["RedPill-Kernel"]["environment"]["PYTHONPATH"] == "/repo/src"
	assert mcp["RedPill-Kernel-Direct"]["enabled"] is False
	assert mcp["RedPill-Kernel-Direct"]["command"][0] == "/usr/bin/uv"


def test_seed_fallback_directo_sin_backend():
	cfg = _render(MCP_SHARED="false", MCP_DIRECT="true")
	mcp = cfg["mcp"]
	assert mcp["RedPill-Kernel"]["enabled"] is False
	assert mcp["RedPill-Kernel-Direct"]["enabled"] is True
