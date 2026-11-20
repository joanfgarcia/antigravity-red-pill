"""P1 — resolutor único del socket y router card que sí llega al cliente.

Cierra S11 y S17 de AUDIT_R1: el proxy descartaba el `InitializeResult` del
backend (así que el `instructions` del servidor no llegaba a ningún cliente que
pasara por él) y había tres resoluciones distintas de `mcp.sock`, con fallo
silencioso por fail-open cuando no coincidían.
"""

from __future__ import annotations

import types as pytypes

import pytest

from red_pill import mcp_proxy
from red_pill.core import paths


def test_socket_por_defecto_es_el_del_servicio(monkeypatch):
	monkeypatch.delenv("REDPILL_MCP_SOCKET", raising=False)
	assert paths.get_mcp_socket() == paths.get_state_dir() / "mcp.sock"
	assert mcp_proxy.default_socket() == str(paths.get_mcp_socket())


def test_socket_override_por_env(monkeypatch, tmp_path):
	custom = tmp_path / "mcp.sock"
	monkeypatch.setenv("REDPILL_MCP_SOCKET", str(custom))
	assert paths.get_mcp_socket() == custom
	assert mcp_proxy.default_socket() == str(custom)


def test_proxy_anuncia_las_instructions_del_backend():
	"""El router card debe viajar del backend al cliente, no quedarse en el proxy."""
	meta = pytypes.SimpleNamespace(
		serverInfo=pytypes.SimpleNamespace(name="RedPill-Kernel", version="9.9"),
		instructions="Cuando necesites memoria, busca con redpill_search.",
	)
	server = mcp_proxy._proxy_server(meta)
	assert server.name == "RedPill-Kernel"
	assert server.version == "9.9"
	assert server.instructions == meta.instructions


def test_proxy_sin_backend_conserva_su_identidad():
	"""Si el backend no responde, el proxy arranca igual (degradación honesta)."""
	server = mcp_proxy._proxy_server(None)
	assert server.name == "RedPill-Kernel"
	assert server.version == "0.1"
	assert not server.instructions


@pytest.mark.asyncio
async def test_metadatos_degradan_a_none_si_el_socket_no_existe(tmp_path):
	meta = await mcp_proxy._fetch_backend_meta(str(tmp_path / "no-existe.sock"), "opencode")
	assert meta is None
