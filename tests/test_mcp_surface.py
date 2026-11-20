"""Superficie declarada del proxy: full · gateway · lista explícita (P1b).

Lo que se declara no es lo mismo que lo que se puede llamar: en `gateway` el
arnés ve tres tools y llega a las quince nombrando la que quiere. Ese es el
ahorro medido (16.385 → 7.578 tok de arranque en opencode) y el test fija el
contrato para que no se degrade sin darse cuenta.
"""

from __future__ import annotations

from red_pill import mcp_proxy

TODAS = [
	"sovereign_handshake",
	"review_decision",
	"suggest_review",
	"list_decisions",
	"moderate_note",
	"unregister_session",
	"fetch_divergent_turns",
	"try_claim_stage",
	"redpill_search",
	"redpill_call",
	"metabolism_health_api",
	"swarm_orchestrator_api",
	"bunker_memory_api",
	"coro_api",
	"job_manager_api",
]


def test_full_declara_todas(monkeypatch):
	monkeypatch.delenv("REDPILL_SURFACE", raising=False)
	assert mcp_proxy.visible_tools(TODAS) == TODAS


def test_gateway_declara_lo_caliente_y_la_puerta(monkeypatch):
	monkeypatch.setenv("REDPILL_SURFACE", "gateway")
	visibles = mcp_proxy.visible_tools(TODAS)
	assert visibles == ["sovereign_handshake", "redpill_search", "redpill_call", "bunker_memory_api"]
	assert "coro_api" not in visibles, "en gateway coro_api no se declara: se alcanza por redpill_call"


def test_lista_explicita(monkeypatch):
	monkeypatch.setenv("REDPILL_SURFACE", "coro_api,job_manager_api")
	assert mcp_proxy.visible_tools(TODAS) == ["coro_api", "job_manager_api"]


def test_perfil_desconocido_no_vacia_la_superficie(monkeypatch):
	"""Un valor raro no debe dejar al agente sin tools: la lista manda, y si no
	coincide nada el resultado es vacío… pero eso es explícito, no silencioso."""
	monkeypatch.setenv("REDPILL_SURFACE", "gatewayy")
	assert mcp_proxy.visible_tools(TODAS) == []
