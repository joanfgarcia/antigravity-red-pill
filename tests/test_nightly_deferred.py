"""Libro de diferidos por techo (NB-001 F3.2, D-NB-16).

Contrato que fijan estos tests:

1. Diferir dos veces la misma unidad suma DOS noches; `first_deferred_at` no se
   mueve (es la edad de la deuda, no la última visita).
2. Completar la unidad la saca del libro.
3. Una unidad que deja de diferirse más de dos noches se retira sola: el libro no
   es un cementerio (una sesión que ya se procesó no puede seguir contando).
4. La clave es `source:session`, acepte la unidad como trío o ya unida — el
   fan-out la escribe de las dos formas según quién la emita.
5. Sin libro (o corrupto) `load()` devuelve vacío y `record()` escribe: el libro
   nunca puede tumbar la noche.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from red_pill.core import nightly_deferred as libro

UNIT = "opencode:opencode:ses_abc"
OTRA = "opencode:opencode:ses_xyz"


@pytest.fixture
def aislado(tmp_path, monkeypatch):
	monkeypatch.setattr(libro, "get_state_dir", lambda: tmp_path)
	monkeypatch.setattr(libro, "RETAIN_S", 2 * 86400.0)
	return tmp_path


def test_diferir_dos_veces_suma_dos_noches_y_conserva_el_primero(aislado):
	libro.record([UNIT], stage="memento-distill")
	primera = libro.load()[UNIT]["first_deferred_at"]
	libro.record([UNIT], stage="memento-distill")
	entrada = libro.load()[UNIT]
	assert entrada["nights"] == 2
	assert entrada["first_deferred_at"] == primera
	assert entrada["last_deferred_at"] >= primera
	assert entrada["stage"] == "memento-distill"


def test_completar_la_unidad_la_saca_del_libro(aislado):
	libro.record([UNIT, OTRA])
	libro.clear([UNIT])
	libro_actual = libro.load()
	assert UNIT not in libro_actual
	assert OTRA in libro_actual


def test_una_unidad_que_deja_de_diferirse_se_retira(aislado):
	libro.record([UNIT], stage="memento-distill")
	# Se envejece la entrada a mano: el reloj del test no espera dos días.
	datos = json.loads(libro.path().read_text(encoding="utf-8"))
	datos["units"][UNIT]["last_deferred_at"] = time.time() - 3 * 86400.0
	libro.path().write_text(json.dumps(datos), encoding="utf-8")
	assert libro.load() == {}


def test_la_clave_es_source_session_acepte_trio_o_texto(aislado):
	libro.record([("opencode", "opencode:ses_abc"), "opencode:opencode:ses_xyz"][0:1])
	libro.record(["opencode:opencode:ses_xyz"])
	libro_actual = libro.load()
	assert libro_actual[UNIT]["nights"] == 1
	assert libro_actual[OTRA]["nights"] == 1
	assert libro.unit_key("opencode", "opencode:ses_abc") == UNIT


def test_sin_libro_no_falla_y_el_orden_no_explota(aislado):
	assert libro.load() == {}
	assert libro.nights({}, UNIT) == 0
	libro.record([])  # nada que anotar: no crea fichero
	assert not libro.path().exists()


def test_libro_corrupto_es_sin_senal(aislado):
	libro.path().write_text("{no soy json", encoding="utf-8")
	assert libro.load() == {}
	libro.record([UNIT])
	assert libro.load()[UNIT]["nights"] == 1


def test_summary_publica_solo_lo_que_lleva_noches(aislado):
	libro.record([UNIT])
	libro.record([UNIT])
	libro.record([OTRA])
	assert libro.summary() == {UNIT: 2, OTRA: 1}


def test_escritura_atomica_no_deja_temporales(aislado):
	libro.record([UNIT])
	restos = [p for p in Path(aislado).iterdir() if p.name.startswith(".nightly_deferred.")]
	assert restos == []
