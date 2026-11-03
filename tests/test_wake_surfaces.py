"""Superficies de la política de despertar (Fase 5/C3): CLI, MCP, doc y guardia.

El núcleo (`session/wake_policy.py` + `delivery.py`) aterrizó antes que estas
superficies: `describe()` existía sin consumidor, `inbound_blocked()` documentaba
su uso desde `soul_notify` y nadie lo llamaba, y WAKE_POLICY no estaba en
`ENV_REFERENCE`. Estos tests fijan el último kilómetro:

- `red-pill session wake-policy` imprime la matriz vigente (y avisa si está rota).
- `red-pill session inbound` declara/lee la postura; por otra alma, solo Operador.
- La acción MCP `set_inbound` declara la postura del propio leg (canal de confianza).
- `soul_notify` respeta `hold`/`refuse` también en el push directo.
"""

import argparse
import json
import sqlite3
from unittest.mock import patch

import pytest

from red_pill.core import soul_notify
from red_pill.session import wake_policy


@pytest.fixture
def wake_db(tmp_path, monkeypatch):
	"""Fuerza el `session.db` de la política a un fichero temporal.

	`set_inbound`/`get_inbound` resuelven la ruta por defecto al llamar; sin este
	parche los tests de CLI escribirían en la BD real del puesto.
	"""
	db = str(tmp_path / "session.db")

	def _connect(_db_path=None):
		conn = sqlite3.connect(db)
		conn.row_factory = sqlite3.Row
		return conn

	monkeypatch.setattr(wake_policy, "_connect", _connect)
	wake_policy.ensure_schema()
	return db


def _cli(**kw):
	base = {"session_cmd": "", "json": False}
	base.update(kw)
	return argparse.Namespace(**base)


# ── CLI: wake-policy ────────────────────────────────────────────────────────


def test_wake_policy_imprime_las_reglas_vigentes(wake_db, capsys):
	from red_pill.cli_services import handle_session

	handle_session(_cli(session_cmd="wake-policy", json=True))
	info = json.loads(capsys.readouterr().out)
	assert info["config_key"] == "WAKE_POLICY"
	assert "self" in info["relations"] and "chain" in info["relations"]
	assert info["fail_closed"] is False
	assert info["default"] == wake_policy.DEFAULT_POLICY


def test_wake_policy_con_config_rota_avisa_fail_closed(wake_db, capsys, monkeypatch):
	from red_pill.cli_services import handle_session
	from red_pill.config import get_config

	monkeypatch.setenv("WAKE_POLICY", "sin-dos-puntos")
	get_config.cache_clear()
	try:
		handle_session(_cli(session_cmd="wake-policy"))
		out = capsys.readouterr().out
	finally:
		monkeypatch.delenv("WAKE_POLICY", raising=False)
		get_config.cache_clear()
	assert "FAIL-CLOSED" in out
	assert "no se despierta a nadie" in out


# ── CLI: inbound ────────────────────────────────────────────────────────────


def test_inbound_la_sesion_declara_por_si_misma(wake_db, monkeypatch, capsys):
	from red_pill.cli_services import handle_session

	monkeypatch.setenv("REDPILL_CONTINUITY_ID", "alma-propia")
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	handle_session(_cli(session_cmd="inbound", state="hold", continuity=None, originator=None, reason="", list=False))
	assert "→ hold" in capsys.readouterr().out
	assert wake_policy.get_inbound("alma-propia") == "hold"


def test_inbound_por_otra_alma_exige_operador(wake_db, monkeypatch, capsys):
	from red_pill.cli_services import handle_session

	monkeypatch.setenv("REDPILL_CONTINUITY_ID", "alma-una")
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	handle_session(_cli(session_cmd="inbound", state="refuse", continuity="alma-ajena", originator=None, reason="", list=False))
	out = capsys.readouterr().out
	assert "Operador" in out
	assert wake_policy.get_inbound("alma-ajena") == "accept", "no se declaró nada por otra alma"


def test_inbound_con_operador_declara_por_ajenas(wake_db, monkeypatch, capsys):
	from red_pill.cli_services import handle_session

	monkeypatch.delenv("REDPILL_CONTINUITY_ID", raising=False)
	monkeypatch.setenv("REDPILL_OPERATOR", "1")
	handle_session(_cli(session_cmd="inbound", state="hold", continuity="alma-ajena", originator=None, reason="descanso", list=False))
	assert "→ hold" in capsys.readouterr().out
	assert wake_policy.get_inbound("alma-ajena") == "hold"


def test_inbound_sin_estado_lee_la_postura_vigente(wake_db, monkeypatch, capsys):
	from red_pill.cli_services import handle_session

	monkeypatch.setenv("REDPILL_CONTINUITY_ID", "alma-lectora")
	wake_policy.set_inbound("alma-lectora", "refuse")
	handle_session(_cli(session_cmd="inbound", state=None, continuity=None, originator=None, reason="", list=False))
	assert "→ refuse" in capsys.readouterr().out


def test_inbound_sin_alma_conocida_pide_identidad(wake_db, monkeypatch, capsys):
	from red_pill.cli_services import handle_session

	monkeypatch.delenv("REDPILL_CONTINUITY_ID", raising=False)
	handle_session(_cli(session_cmd="inbound", state="hold", continuity=None, originator=None, reason="", list=False))
	assert "falta el alma" in capsys.readouterr().out


# ── MCP: set_inbound ────────────────────────────────────────────────────────


class TestMcpSetInbound:
	@staticmethod
	async def _call(arguments, session):
		from red_pill.mcp_server import handle_set_inbound

		async def _fake_caller(_args):
			return session

		with patch("red_pill.mcp_server._caller_session", new=_fake_caller):
			result = await handle_set_inbound(arguments)
		return result[0].text

	@pytest.mark.asyncio
	async def test_declara_la_postura_de_su_propio_leg(self, wake_db):
		out = await self._call({"state": "hold", "reason": "focus"}, {"continuity_id": "alma-mcp", "originator": "opencode:m1"})
		assert "→ hold" in out
		assert wake_policy.get_inbound("alma-mcp", originator="opencode:m1") == "hold"

	@pytest.mark.asyncio
	async def test_sin_cuerpo_o_alma_no_declara_nada(self, wake_db):
		out = await self._call({"state": "refuse"}, {"continuity_id": "", "originator": ""})
		assert "fail-closed" in out
		out2 = await self._call({"state": "refuse"}, {"continuity_id": "alma-x", "originator": "sinseparador"})
		assert "fail-closed" in out2

	@pytest.mark.asyncio
	async def test_estado_desconocido_se_rechaza(self, wake_db):
		out = await self._call({"state": "dormir"}, {"continuity_id": "alma-mcp", "originator": "opencode:m1"})
		assert "estado desconocido" in out

	def test_la_accion_esta_registrada_bajo_el_padre_oficial(self):
		"""`set_inbound` es una acción de `swarm_orchestrator_api`, no una tool suelta."""
		from red_pill.mcp_server import registry  # noqa: F401  (el import registra)

		assert "set_inbound" in registry._actions.get("swarm_orchestrator_api", {})


# ── soul_notify: el push directo respeta la postura ─────────────────────────


def _push(monkeypatch, soul, originator="opencode:ses_a"):
	delivered = []
	monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
	monkeypatch.setitem(soul_notify._TRANSPORTS, "cli", lambda s, t: delivered.append((s, t)) or True)
	ok = soul_notify.notify_soul(soul, "hola", originator=originator)
	return ok, delivered


def test_hold_apaga_el_aviso_de_fin_de_job(monkeypatch):
	monkeypatch.setattr(wake_policy, "inbound_blocked", lambda soul, **kw: "inbound_hold")
	ok, delivered = _push(monkeypatch, "alma-1")
	assert ok is False and delivered == []


def test_refuse_apaga_el_aviso(monkeypatch):
	monkeypatch.setattr(wake_policy, "inbound_blocked", lambda soul, **kw: "inbound_refuse")
	ok, delivered = _push(monkeypatch, "alma-1")
	assert ok is False and delivered == []


def test_accept_deja_pasar_la_cadena_de_mando_del_job(monkeypatch):
	monkeypatch.setattr(wake_policy, "inbound_blocked", lambda soul, **kw: None)
	ok, delivered = _push(monkeypatch, "alma-1")
	assert ok is True and delivered == [("ses_a", "hola")]


def test_estado_ilegible_es_fail_closed_no_despertar(monkeypatch):
	def _boom(*_a, **_kw):
		raise RuntimeError("bd caída")

	monkeypatch.setattr(wake_policy, "inbound_blocked", _boom)
	ok, delivered = _push(monkeypatch, "alma-1")
	assert ok is False and delivered == []


# ── delivery: el diagnóstico de la política viaja en el informe ─────────────


def test_deliver_events_reporta_la_politica(tmp_path):
	from red_pill.session import delivery

	report = delivery.deliver_events("alma-sin-eventos", db_path=str(tmp_path / "delivery.db"))
	policy = report.get("policy") or {}
	assert policy.get("error") in (None, "")
	assert isinstance(policy.get("rules"), list)
