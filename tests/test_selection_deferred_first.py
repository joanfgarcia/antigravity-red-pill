"""Lo diferido vuelve PRIMERO en la selección (NB-001 F3.2, D-NB-16).

Contrato que fijan estos tests:

1. Con el flag OFF el orden es **byte-idéntico** al de siempre (stale-first): el
   libro puede tener entradas y no se miran.
2. Con el flag ON manda `noches desc`; a igualdad, **el más barato**; y solo
   después `stale-first`.
3. El desempate por coste no es cosmético: con presupuesto ajustado, la pequeña
   diferida entra y la monstruo NO, mientras que con el orden antiguo entraba la
   monstruo (o la stale) y la pequeña quedaba fuera otro día más.
"""

from __future__ import annotations

import pytest

import red_pill.config as cfg
from red_pill.core import nightly_deferred as libro
from red_pill.memento.agentic.selection import select_targets

MONSTER = ("opencode", "opencode:ses_monster", "missing")
PEQUE = ("opencode", "opencode:ses_peque", "missing")
STALE = ("opencode", "opencode:ses_stale", "stale")

MSGS = {
	"opencode:ses_monster": 100,
	"opencode:ses_peque": 5,
	"opencode:ses_stale": 1,
}


class _Registry:
	"""Registry mínimo: `message_count` lee `state['registry'][source][sid]`."""

	def __init__(self, msgs):
		self.state = {"registry": {"opencode": {sid: {"message_count": n} for sid, n in msgs.items()}}}


@pytest.fixture
def registro():
	return _Registry(MSGS)


@pytest.fixture
def estado(tmp_path, monkeypatch):
	monkeypatch.setattr(libro, "get_state_dir", lambda: tmp_path)
	return tmp_path


def _con_flag(monkeypatch, on: bool):
	monkeypatch.setattr(cfg, "NIGHTLY_DEFERRED_FIRST_ENABLED", on, raising=False)


def test_flag_off_el_orden_es_el_de_siempre(monkeypatch, estado, registro):
	_con_flag(monkeypatch, False)
	libro.record(["opencode:opencode:ses_peque"], stage="memento-distill")
	pending = [MONSTER, PEQUE, STALE]
	chosen = select_targets(pending, limit=10, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen] == [t[1] for t in sorted(pending, key=lambda t: t[2] != "stale")]


def test_flag_on_los_diferidos_van_primero(monkeypatch, estado, registro):
	_con_flag(monkeypatch, True)
	libro.record(["opencode:opencode:ses_peque"], stage="memento-distill")
	chosen = select_targets([MONSTER, PEQUE, STALE], limit=10, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen] == ["opencode:ses_peque", "opencode:ses_stale", "opencode:ses_monster"]


def test_mas_noches_gana_a_menos_noches(monkeypatch, estado, registro):
	_con_flag(monkeypatch, True)
	libro.record(["opencode:opencode:ses_monster"])  # 1 noche
	libro.record(["opencode:opencode:ses_peque"])  # 1 noche
	libro.record(["opencode:opencode:ses_peque"])  # 2 noches
	chosen = select_targets([MONSTER, PEQUE, STALE], limit=10, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen][:2] == ["opencode:ses_peque", "opencode:ses_monster"]


def test_a_igualdad_de_noches_gana_el_mas_barato(monkeypatch, estado, registro):
	_con_flag(monkeypatch, True)
	libro.record(["opencode:opencode:ses_monster"])
	libro.record(["opencode:opencode:ses_peque"])
	chosen = select_targets([MONSTER, PEQUE], limit=10, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen] == ["opencode:ses_peque", "opencode:ses_monster"]


def test_el_desempate_por_coste_salva_a_la_pequena_del_presupuesto(monkeypatch, estado, registro):
	"""Con 10 mensajes de presupuesto: el orden antiguo se lo come la monstruo."""
	_con_flag(monkeypatch, False)
	viejo = select_targets([MONSTER, PEQUE, STALE], limit=10, msg_limit=10, registry=registro)
	assert [t[1] for t in viejo] == ["opencode:ses_stale"], "la monstruo bloquea con `break`: solo entra la stale"

	_con_flag(monkeypatch, True)
	libro.record(["opencode:opencode:ses_peque"])
	nuevo = select_targets([MONSTER, PEQUE, STALE], limit=10, msg_limit=10, registry=registro)
	assert [t[1] for t in nuevo] == ["opencode:ses_peque", "opencode:ses_stale"], "la diferida entra "
	assert all(t[1] != "opencode:ses_monster" for t in nuevo)


def test_flag_on_sin_libro_no_cambia_nada(monkeypatch, estado, registro):
	_con_flag(monkeypatch, True)
	pending = [MONSTER, PEQUE, STALE]
	chosen = select_targets(pending, limit=10, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen] == [t[1] for t in sorted(pending, key=lambda t: t[2] != "stale")]


def test_limit_cero_sigue_devolviendo_todo(monkeypatch, estado, registro):
	_con_flag(monkeypatch, True)
	libro.record(["opencode:opencode:ses_peque"])
	chosen = select_targets([MONSTER, PEQUE], limit=0, msg_limit=0, registry=registro)
	assert [t[1] for t in chosen] == ["opencode:ses_monster", "opencode:ses_peque"]
