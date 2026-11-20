"""Tests de la superficie (P1b): perfil por petición y puerta única.

Lo que se protege:

- El **default no cambia el comportamiento** (`full`): un perfil que ahorra tokens
  no puede romper a quien no lo declara.
- `surface` viaja **por petición** (contextvar del proxy), no por env global: el
  backend es un proceso para N clientes.
- La puerta única devuelve el esquema como texto y `redpill_call` da errores
  estructurados, que es lo único que el proxy deja pasar (no `isError`).
"""

from __future__ import annotations

import json

import pytest

from red_pill import mcp_server as kernel
from red_pill.registry import registry


@pytest.fixture(autouse=True)
def _surface_limpia(monkeypatch):
	monkeypatch.delenv("REDPILL_TOOLS_PROFILE", raising=False)
	token = kernel._shared_identity_var.set(None)
	yield
	kernel._shared_identity_var.reset(token)


def test_default_es_full_para_no_romper_a_nadie():
	assert kernel._surface() == "full"


def test_surface_viaja_por_peticion(monkeypatch):
	token = kernel._shared_identity_var.set({"originator": "opencode:x", "surface": "gateway"})
	try:
		assert kernel._surface() == "gateway"
	finally:
		kernel._shared_identity_var.reset(token)
	assert kernel._surface() == "full"


def test_env_es_solo_suelo(monkeypatch):
	monkeypatch.setenv("REDPILL_TOOLS_PROFILE", "none")
	assert kernel._surface() == "none"
	token = kernel._shared_identity_var.set({"surface": "gateway"})
	try:
		assert kernel._surface() == "gateway", "la petición manda sobre el suelo del proceso"
	finally:
		kernel._shared_identity_var.reset(token)


@pytest.mark.asyncio
async def test_list_tools_por_perfil():
	token = kernel._shared_identity_var.set({"surface": "gateway"})
	try:
		tools = await kernel.handle_list_tools()
	finally:
		kernel._shared_identity_var.reset(token)
	assert {t.name for t in tools} == set(kernel.GATEWAY_TOOLS)

	token = kernel._shared_identity_var.set({"surface": "none"})
	try:
		assert await kernel.handle_list_tools() == []
	finally:
		kernel._shared_identity_var.reset(token)


@pytest.mark.asyncio
async def test_list_tools_full_es_todo():
	every = {t.name for t in registry.get_tools()}
	declared = {t.name for t in await kernel.handle_list_tools()}
	assert declared == every


@pytest.mark.asyncio
async def test_search_devuelve_esquema_como_texto():
	out = await kernel.handle_redpill_search({"query": "memoria recall", "limit": 3})
	payload = json.loads(out[0].text)
	assert payload["results"]
	nombres = [r["name"] for r in payload["results"]]
	assert "bunker_memory_api" in nombres
	first = payload["results"][0]
	assert first["schema"]["type"] == "object"
	assert first["description"]


@pytest.mark.asyncio
async def test_search_sin_coincidencias_no_miente():
	out = await kernel.handle_redpill_search({"query": "kubernetes helm chart"})
	payload = json.loads(out[0].text)
	assert payload["results"] == []


@pytest.mark.asyncio
async def test_call_desconocida_devuelve_error_estructurado():
	out = await kernel.handle_redpill_call({"name": "no_existe", "arguments": {}})
	payload = json.loads(out[0].text)
	assert payload["error"] == "unknown_tool"
	assert isinstance(payload["hints"], list)


@pytest.mark.asyncio
async def test_call_arguments_no_objeto_es_invalid_arguments():
	out = await kernel.handle_redpill_call({"name": "redpill_search", "arguments": "no"})
	payload = json.loads(out[0].text)
	assert payload["error"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_call_invoca_la_tool():
	out = await kernel.handle_redpill_call({"name": "redpill_search", "arguments": {"query": "jobs"}})
	payload = json.loads(out[0].text)
	assert payload["results"]
