"""Seed V2 de opencode: proxy compartido por defecto y directo como fallback.

El repo sólo soporta OpenCode V2+ (2026-10-27): el seed vive en
`seeds/opencode/settings/v2/` y usa el esquema V2 (`mcp.servers` + `disabled`),
no el `enabled` de V1.
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Template

SEED = Path(__file__).resolve().parents[1] / "seeds" / "opencode" / "settings" / "v2" / "opencode.jsonc"
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
	mcp = cfg["mcp"]["servers"]
	assert mcp["RedPill-Kernel"]["disabled"] is False
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
	assert mcp["RedPill-Kernel-Direct"]["disabled"] is True
	assert mcp["RedPill-Kernel-Direct"]["command"][0] == "/usr/bin/uv"


def test_seed_fallback_directo_sin_backend():
	cfg = _render(MCP_SHARED="false", MCP_DIRECT="true")
	mcp = cfg["mcp"]["servers"]
	assert mcp["RedPill-Kernel"]["disabled"] is True
	assert mcp["RedPill-Kernel-Direct"]["disabled"] is False


def test_seed_no_usa_esquema_v1():
	"""Blindaje V2+: `enabled` es de V1 y opencode V2 no lo lee."""
	cfg = _render()
	for name, server in cfg["mcp"]["servers"].items():
		assert "enabled" not in server, f"{name} usa el campo V1 `enabled`"
