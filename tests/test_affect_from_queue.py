"""El afecto sale de los turnos vivos, no de los engramas ascendidos (2026-11-03).

`get_dominant_mood` leía `work/social_memories`: lo que ascendió la noche
anterior (o de hace seis días si la ingesta se paró). No puede decir cómo está
el Operador en el turno. Estos tests fijan el camino nuevo: léxico sobre
`memory_queue.prompt`, estado en `state/affect.json` con TTL y la paleta
anger/fear→red, anxiety→orange, joy→yellow, calm→cyan, neutral→gray.
"""

import json
import sqlite3
import time

import pytest

from red_pill.utils import operator_affect as affect


@pytest.fixture
def entorno(tmp_path, monkeypatch):
	"""Cola y estado temporales: ni la BD real ni el `affect.json` del puesto."""
	queue_dir = tmp_path / "queue"
	queue_dir.mkdir()
	state_dir = tmp_path / "state"
	state_dir.mkdir()
	db = queue_dir / "bunker_queue.db"
	with sqlite3.connect(db) as conn:
		conn.execute("CREATE TABLE memory_queue (prompt TEXT, created_at REAL)")
	monkeypatch.setattr("red_pill.core.paths.get_queue_dir", lambda: queue_dir)
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: state_dir)
	return {"db": db, "state": state_dir / "affect.json"}


def _turno(db, prompt, age_s=0):
	with sqlite3.connect(db) as conn:
		conn.execute("INSERT INTO memory_queue (prompt, created_at) VALUES (?, ?)", (prompt, time.time() - age_s))


def test_clasifica_enfado_y_miedo_en_rojo():
	resultado = affect.classify(["estoy harto de que no funcione", "me da miedo perder memoria"])
	assert resultado["color"] == "red"
	assert resultado["emotion"] in ("anger", "fear")
	assert resultado["intensity"] > 0
	assert resultado["evidence"]


def test_clasifica_ansiedad_en_naranja_y_calma_en_cian():
	assert affect.classify(["estoy muy agobiado con esto"])["color"] == "orange"
	assert affect.classify(["lo dejamos, tranquilo, mañana será otro día"])["color"] == "cyan"


def test_sin_pistas_es_gris_neutro():
	resultado = affect.classify(["revisa el log del job"])
	assert resultado == {"emotion": "neutral", "color": "gray", "intensity": 0.0, "hits": 0, "evidence": []}


def test_el_estado_sale_de_la_cola_y_se_escribe_en_disco(entorno):
	_turno(entorno["db"], "me da miedo que se pierda la memoria", age_s=60)
	_turno(entorno["db"], "estoy harto del fallo", age_s=30)

	estado = affect.current()

	assert estado and estado["color"] == "red"
	assert estado["turns"] == 2
	assert json.loads(entorno["state"].read_text())["color"] == "red"


def test_los_bloques_inyectados_no_son_la_voz_del_operador(entorno):
	"""El arnés guarda `<user_rules>…` como `prompt`: si llevan "calma", no pintan."""
	_turno(entorno["db"], "<user_rules>\n<constraint>mantén la calma y el tono</constraint>", age_s=20)
	_turno(entorno["db"], "revisa el log del job", age_s=10)

	estado = affect.current()

	assert estado["turns"] == 1
	assert estado["color"] == "gray"


def test_un_estado_fresco_no_se_recalcula(entorno):
	entorno["state"].write_text(json.dumps({"color": "yellow", "emotion": "joy", "computed_at": time.time(), "turns": 1}))
	_turno(entorno["db"], "me da miedo", age_s=10)

	estado = affect.current()

	assert estado["color"] == "yellow", "dentro del TTL manda el fichero"


def test_un_estado_caducado_se_recalcula(entorno):
	entorno["state"].write_text(json.dumps({"color": "yellow", "emotion": "joy", "computed_at": time.time() - 3600, "turns": 1}))
	_turno(entorno["db"], "me da miedo", age_s=10)

	assert affect.current()["color"] == "red"


def test_sin_turnos_en_la_ventana_se_conserva_lo_ultimo(entorno):
	entorno["state"].write_text(json.dumps({"color": "orange", "emotion": "anxiety", "computed_at": time.time() - 3600, "turns": 1}))
	_turno(entorno["db"], "esto es de hace dos días", age_s=3 * 86400)

	assert affect.current()["color"] == "orange"


def test_get_current_sync_state_usa_el_afecto_de_la_cola(monkeypatch):
	from red_pill.utils import tone_analyzer

	monkeypatch.setattr("red_pill.utils.operator_affect.current", lambda: {"color": "red", "emotion": "fear", "turns": 3})
	estado = tone_analyzer.get_current_sync_state()
	assert estado["mood"] == "red"
	assert estado["directive"]  # la directiva del rojo existe


def test_sin_afecto_cae_al_camino_antiguo(monkeypatch):
	from red_pill.utils import tone_analyzer

	monkeypatch.setattr("red_pill.utils.operator_affect.current", lambda: None)
	monkeypatch.setattr(tone_analyzer.ToneAnalyzer, "get_dominant_mood", staticmethod(lambda manager=None: "blue"))
	assert tone_analyzer.get_current_sync_state()["mood"] == "blue"
