"""Tests de las rutas del hook (RFC-HARNESS-001 · P1).

Se prueba la lógica de los handlers (que es donde está el contrato) y el
cableado de rutas con su middleware. El objetivo es que un fallo aquí no sea
silencioso: payload malo → 4xx, ack repetido → duplicado sin re-sellar, y el
endpoint declarado en la app.
"""

from __future__ import annotations

import pytest

from red_pill.hooks import routes
from red_pill.hooks.context_api import HookPayloadError


@pytest.fixture(autouse=True)
def _limpia_cache():
	routes.reset_caches()
	yield
	routes.reset_caches()


def test_app_declara_las_dos_rutas():
	from red_pill.mcp_backend import build_app

	paths = [getattr(r, "path", None) for r in build_app().routes]
	assert "/hook/context" in paths
	assert "/hook/ack" in paths


def test_generation_es_un_entero_y_sube(monkeypatch, tmp_path):
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	base = routes.generation()
	assert isinstance(base, int)
	assert routes.bump_generation() == base + 1
	assert routes.generation() == base + 1


@pytest.mark.asyncio
async def test_need_poll_no_devuelve_identidad_ni_bloques_pesados():
	res = await routes.handle_context({"session_id": "ses_test_poll", "harness": "opencode", "need": "poll", "turn": 1, "model": "m"})
	assert res["hint"] == "none"
	assert all(b["kind"] != "identity" for b in res["blocks"])
	assert res["delivery_id"]


@pytest.mark.asyncio
async def test_full_sin_cache_devuelve_retry_full_y_no_bloquea():
	"""El arranque en frío no espera 2,3 s: encarga y pide que se reintente."""
	res = await routes.handle_context({"session_id": "ses_test_full", "harness": "opencode", "need": "full", "turn": 1, "model": "m"})
	assert res["hint"] == "retry_full"
	assert all(b["kind"] != "identity" for b in res["blocks"])


@pytest.mark.asyncio
async def test_payload_invalido_es_error_de_cliente():
	with pytest.raises(HookPayloadError):
		await routes.handle_context({"harness": "opencode", "need": "light"})


@pytest.mark.asyncio
async def test_ack_es_idempotente(monkeypatch, tmp_path):
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	payload = {
		"session_id": "ses_test_ack",
		"harness": "opencode",
		"need": "poll",
		"turn": 4,
		"delivery_id": "delivery-fija",
		"seq": 0,
		"delivered": True,
		"response": "",
	}
	first = await routes.handle_ack(payload)
	second = await routes.handle_ack(payload)
	assert first["duplicate"] is False
	assert second["duplicate"] is True
	assert second["sealed"] is False


def test_los_escritores_de_directivas_mueven_la_generacion(monkeypatch, tmp_path):
	"""S12: si un escritor de identidad no mueve `generation`, la caché del hook
	sirve directivas viejas y el resync nunca se entera."""
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	from red_pill import seed
	from red_pill.core import pact

	antes = routes.generation()
	seed._bump_generation()
	seed._bump_generation()  # el helper es idempotente en forma, no en efecto
	despues = routes.generation()
	assert despues >= antes + 2
	pact._bump_generation()
	assert routes.generation() == despues + 1


@pytest.mark.asyncio
async def test_el_hook_escribe_el_bridge_del_arnes(monkeypatch, tmp_path):
	"""P4: sin bridge, las llamadas MCP de `pi` no resuelven cuerpo (su identidad
	sólo viajaba como argumento del modelo, que es lo que dejamos de aceptar)."""
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

	from red_pill import mcp_server
	from red_pill.core.paths import get_state_dir

	await routes.handle_context(
		{
			"session_id": "ses_pi_bridge",
			"harness": "pi",
			"need": "poll",
			"turn": 1,
			"workdir": "/tmp/ws",
		}
	)
	bridge = get_state_dir() / "pi_session.json"
	assert bridge.is_file()
	data = __import__("json").loads(bridge.read_text(encoding="utf-8"))
	assert data["provider"] == "pi"
	assert data["session_id"] == "ses_pi_bridge"
	assert data["workdir"] == "/tmp/ws"
	# y el kernel lo lee por el canal de confianza
	entry = mcp_server._harness_bridge("pi")
	assert entry["originator"] == "pi:ses_pi_bridge"
