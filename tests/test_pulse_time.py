"""El reloj del handshake (2026-10-31).

Sin esto no puedo distinguir "ayer" de "hace dos turnos", y una memoria que
confunde esas dos escalas miente sobre el tiempo. Tres escalas: turno (minutos),
pausa dentro de la sesión (horas) y sesión nueva (días).
"""

import json
import os

import pytest

from red_pill.utils import pulse


@pytest.fixture
def heartbeat(tmp_path, monkeypatch):
	"""pulse.json aislado por test."""
	f = tmp_path / "pulse.json"
	monkeypatch.setattr(pulse, "HEARTBEAT_FILE", str(f))
	return f


def _escribir(path, **kw):
	path.write_text(json.dumps(kw), encoding="utf-8")


def test_linea_sin_historial_solo_da_la_hora(heartbeat):
	linea = pulse.time_line(now=1793500000.0)
	assert linea.startswith("- Ahora: ")
	assert "turno anterior" not in linea
	assert "sesión desde" not in linea


def test_delta_del_turno_y_sesion(heartbeat):
	now = 1793500000.0
	_escribir(heartbeat, last_interaction=now - 180, prev_interaction=now - 900, session_start=now - 3600)
	linea = pulse.time_line(now=now)
	assert "turno anterior: hace 3m" in linea
	assert "sesión desde" in linea and "1h" in linea


def test_delta_en_segundos_cuando_son_dos_turnos_seguidos(heartbeat):
	now = 1793500000.0
	_escribir(heartbeat, last_interaction=now - 25, prev_interaction=now - 60, session_start=now - 120)
	assert "hace 25s" in pulse.time_line(now=now)


def test_record_interaction_conserva_la_sesion_si_el_hueco_es_corto(heartbeat):
	now = 1793500000.0
	inicio = now - 7200
	_escribir(heartbeat, last_interaction=now - 60, prev_interaction=now - 600, session_start=inicio)
	pulse.record_interaction()
	data = json.loads(heartbeat.read_text(encoding="utf-8"))
	assert data["session_start"] == inicio
	assert data["prev_interaction"] == now - 60


def test_record_interaction_abre_sesion_nueva_tras_ausencia(heartbeat, monkeypatch):
	import red_pill.config as cfg

	now = 1793500000.0
	monkeypatch.setattr(cfg, "CADENCE_ABSENCE_THRESHOLD", 3600)
	_escribir(heartbeat, last_interaction=now - 86400, prev_interaction=0.0, session_start=now - 90000)
	pulse.record_interaction()
	data = json.loads(heartbeat.read_text(encoding="utf-8"))
	# record_interaction usa el reloj REAL; lo que se comprueba es que la sesión
	# nueva arranca en este mismo turno, no que coincida con el `now` del test.
	assert data["session_start"] == data["last_interaction"]


def test_primera_vez_no_hay_prev(heartbeat):
	pulse.record_interaction()
	data = json.loads(heartbeat.read_text(encoding="utf-8"))
	assert data["prev_interaction"] == 0.0
	assert data["session_start"] == data["last_interaction"]


def test_fichero_corrupto_no_rompe(heartbeat):
	heartbeat.write_text("{ esto no es json", encoding="utf-8")
	assert pulse.time_line(now=1793500000.0).startswith("- Ahora: ")
	pulse.record_interaction()  # no debe lanzar
	assert os.path.exists(pulse.HEARTBEAT_FILE)
