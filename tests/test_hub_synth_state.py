"""Tests del espejo read-only del estado de hubs (`scripts/hub_synth_state.py`).

El espejo replica la compuerta de `_synthesize_one` para poder mirar la noche
sin abrir Qdrant a mano. Lo que se fija aquí es la **aritmética de la espera**,
que es donde el diagnóstico se equivoca de verdad:

- un marcador de OTRA entrada no es una espera (el input cambió: paga hoy),
- dentro de la ventana no se paga, y `remaining` es lo que falta, no lo andado,
- un marcador legacy SIN fecha cuenta como caducado (se gasta, no se pierde),
- `WAIT_RETRY_DAYS=0` es espera INDEFINIDA (conducta previa al 2026-11-12), no
  caducidad inmediata — el cero desactiva la caducidad, no la acelera.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hub_synth_state.py"


def _load():
	spec = importlib.util.spec_from_file_location("hub_synth_state_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = mod
	spec.loader.exec_module(mod)
	return mod


def test_sin_marcador_paga_hoy():
	mod = _load()
	assert mod.gate_verdict("", 0, "abc", None, max_rejections=2, window_days=7.0) == ("open", None)


def test_marcador_de_otra_entrada_no_es_espera():
	mod = _load()
	# Se rechazó 5 veces, pero la entrada cambió (hash distinto): merece intento.
	assert mod.gate_verdict("viejo", 5, "nuevo", 0.2, max_rejections=2, window_days=7.0) == ("open", None)


def test_bajo_el_tope_sigue_pagando():
	mod = _load()
	assert mod.gate_verdict("abc", 1, "abc", 0.2, max_rejections=2, window_days=7.0) == ("open", None)


def test_dentro_de_la_ventana_espera_y_dice_lo_que_falta():
	mod = _load()
	verdict, remaining = mod.gate_verdict("abc", 2, "abc", 2.0, max_rejections=2, window_days=7.0)
	assert verdict == "waiting"
	assert remaining == 5.0


def test_marcador_legacy_sin_fecha_caduca():
	mod = _load()
	assert mod.gate_verdict("abc", 2, "abc", None, max_rejections=2, window_days=7.0) == ("expires_now", None)


def test_ventana_cero_es_espera_indefinida_no_caducidad():
	mod = _load()
	assert mod.gate_verdict("abc", 2, "abc", 999.0, max_rejections=2, window_days=0.0) == ("waiting", None)


def test_compuerta_apagada_nunca_espera():
	mod = _load()
	assert mod.gate_verdict("abc", 99, "abc", 0.1, max_rejections=0, window_days=7.0) == ("open", None)
