"""Tests de las rutas del hook (RFC-HARNESS-001 · P1).

Se prueba la lógica de los handlers (que es donde está el contrato) y el
cableado de rutas con su middleware. El objetivo es que un fallo aquí no sea
silencioso: payload malo → 4xx, ack repetido → duplicado sin re-sellar, y el
endpoint declarado en la app.
"""

from __future__ import annotations

import json
import time

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
async def test_light_cuenta_la_telemetria_en_el_kernel(monkeypatch):
	"""El contrato no pide contadores: sin ellos, `light` no decía nada.

	`need=light` promete «la línea de telemetría», pero ningún arnés manda
	`open_loops`/`pain`/`jobs` (no están en el contrato §2). Si el servidor los
	lee del payload y nadie los pone, el bloque `telemetry` no existe y el
	agente sólo ve OPEN LOOPS llamando a la tool: justo el viaje que el hook
	venía a ahorrar.
	"""
	monkeypatch.setattr(routes, "_kernel_telemetry_text", lambda: "OPEN LOOPS: 11 shards OPEN · dolor 7")
	monkeypatch.setattr(routes, "_clock_line", lambda: "- Ahora: 2026-11-22 00:14 (dom)")
	res = await routes.handle_context(
		{"session_id": "ses_test_light", "harness": "opencode", "need": "light", "turn": 2, "model": "m"}
	)
	telemetria = [b["text"] for b in res["blocks"] if b["kind"] == "telemetry"]
	assert telemetria == ["- Ahora: 2026-11-22 00:14 (dom) · OPEN LOOPS: 11 shards OPEN · dolor 7"]


@pytest.mark.asyncio
async def test_light_lleva_el_reloj_del_turno(monkeypatch, tmp_path):
	"""Sin hora, el agente confunde el domingo de madrugada con el domingo de día.

	El arnés sólo manda la fecha. El reloj del turno (`pulse.time_line`) tiene que
	viajar en el bloque `telemetry` aunque no haya contadores ni estado del Búnker.
	"""
	monkeypatch.setattr(routes, "_kernel_telemetry_text", lambda: "")
	heartbeat = tmp_path / "pulse.json"
	heartbeat.write_text(json.dumps({"last_interaction": time.time(), "session_start": time.time()}), encoding="utf-8")
	monkeypatch.setattr("red_pill.utils.pulse.HEARTBEAT_FILE", str(heartbeat))
	res = await routes.handle_context(
		{"session_id": "ses_test_clock", "harness": "opencode", "need": "light", "turn": 2, "model": "m"}
	)
	telemetria = [b["text"] for b in res["blocks"] if b["kind"] == "telemetry"]
	assert telemetria, "el reloj no llegó al agente"
	assert telemetria[0].startswith("- Ahora: ")
	assert "turno anterior" in telemetria[0]


def test_el_reloj_no_tumba_el_turno_si_falta_el_heartbeat(monkeypatch):
	monkeypatch.setattr("red_pill.utils.pulse.HEARTBEAT_FILE", "/nonexistent/pulse.json")
	assert routes._clock_line().startswith("- Ahora: ")


@pytest.mark.asyncio
async def test_light_respeta_los_contadores_si_el_cliente_los_manda(monkeypatch):
	"""Compatibilidad: un cliente que sí manda números manda él."""
	monkeypatch.setattr(routes, "_kernel_telemetry_text", lambda: "no debería usarse")
	monkeypatch.setattr(routes, "_clock_line", lambda: "- Ahora: 2026-11-22 00:14 (dom)")
	res = await routes.handle_context(
		{
			"session_id": "ses_test_light2",
			"harness": "opencode",
			"need": "light",
			"turn": 2,
			"model": "m",
			"open_loops": 4,
			"pain": 1,
		}
	)
	telemetria = [b["text"] for b in res["blocks"] if b["kind"] == "telemetry"]
	assert telemetria and "OPEN LOOPS 4" in telemetria[0] and "dolor 1" in telemetria[0]


def _estado(monkeypatch, tmp_path, payload: dict):
	monkeypatch.setattr(routes, "_state_path", lambda: tmp_path / "bunker_state.json")
	(tmp_path / "bunker_state.json").write_text(json.dumps(payload), encoding="utf-8")
	monkeypatch.setattr("red_pill.core.open_loops.open_loops_line", lambda *a, **k: "")


def test_telemetria_del_kernel_cuenta_dolor_y_minions(monkeypatch, tmp_path):
	_estado(monkeypatch, tmp_path, {"timestamp": time.time(), "signals": {"active": 7}, "minions": {"unread": 3}})
	assert routes._kernel_telemetry_text() == "dolor 7 · minions 3"


def test_telemetria_del_kernel_ignora_el_estado_rancio(monkeypatch, tmp_path):
	"""Un `bunker_state.json` de hace media hora no es el presente."""
	_estado(monkeypatch, tmp_path, {"timestamp": time.time() - 3600, "signals": {"active": 7}, "minions": {"unread": 3}})
	assert routes._kernel_telemetry_text() == ""


def test_telemetria_del_kernel_es_silenciosa_si_no_hay_nada(monkeypatch, tmp_path):
	_estado(monkeypatch, tmp_path, {"timestamp": time.time()})
	assert routes._kernel_telemetry_text() == ""


def test_el_puente_no_pierde_el_workdir_si_el_arnes_no_lo_manda(monkeypatch, tmp_path):
	"""`/hook/context` no recibe `workdir` (no está en el contrato §2).

	Un `""` no puede borrar el que escribió el scribe: `open_loops_line()`
	resuelve el workspace con este puente y se ejecuta en el MISMO request, así
	que el borrado hace que la línea cuente shards y ramas del workspace de otro
	arnés —o del cwd del backend, que es el checkout del kernel.
	"""
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	ws = tmp_path / "ws"
	ws.mkdir()
	routes._write_bridge("opencode", "ses_bridge", str(ws))
	routes._write_bridge("opencode", "ses_bridge", "")
	data = json.loads((routes.get_state_dir() / "opencode_session.json").read_text(encoding="utf-8"))
	assert data["workdir"] == str(ws)
	assert data["session_id"] == "ses_bridge"


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
