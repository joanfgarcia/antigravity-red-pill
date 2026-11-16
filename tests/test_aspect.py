"""The aspect palette, its validator, and the precedence it changes (RFC-ASP-001 F1).

Contract these tests fix: the palette covers only colours the system already
knows, it describes and never prescribes (it must not leak into the tone map), a
declaration outside the palette fails listing the valid ones, and the declared
aspect wins over the calculated value without becoming a source of behaviour.
"""

import json

import pytest

import red_pill.identity as identity
from red_pill.config import CHROMA_TONE_MAPPING
from red_pill.core import aspect
from red_pill.metabolism import evolution
from red_pill.utils import tone_analyzer
from red_pill.utils.tone_analyzer import ToneAnalyzer


class _Point:
	def __init__(self, **payload):
		self.payload = payload


class _Client:
	def __init__(self, points):
		self._points = points

	def scroll(self, **_kw):
		return self._points, None


class _Manager:
	def __init__(self, points):
		self.client = _Client(points)


@pytest.fixture
def estado(tmp_path, monkeypatch):
	monkeypatch.setattr(identity, "get_state_dir", lambda: tmp_path)
	return tmp_path


def _escribir_identidad(estado, **datos):
	(estado / "identity.json").write_text(json.dumps(datos), encoding="utf-8")


def test_palette_cubre_colores_del_sistema():
	colores = aspect.colors()
	assert colores, "paleta vacía: el YAML no se pudo leer"
	assert set(colores) <= set(CHROMA_TONE_MAPPING), f"colores inventados: {set(colores) - set(CHROMA_TONE_MAPPING)}"


def test_cada_color_tiene_etiqueta_y_descripcion():
	for color, dato in aspect.palette().items():
		assert dato.get("label"), f"{color} sin etiqueta"
		assert dato.get("desc"), f"{color} sin descripción"
		assert len(str(dato["label"]).split()) == 1, f"{color}: la etiqueta es una palabra"


def test_la_paleta_no_es_el_mapa_de_tono():
	"""D-04: el aspecto describe, no prescribe. Nada de la paleta puede ser una directiva."""
	directivas = set(CHROMA_TONE_MAPPING.values())
	for color, dato in aspect.palette().items():
		assert dato["desc"] not in directivas, f"{color}: su descripción es una directiva de conducta"
		assert dato["label"] not in CHROMA_TONE_MAPPING, f"{color}: su etiqueta colisiona con una clave de tono"


def test_validate_normaliza_mayusculas_y_espacios():
	assert aspect.validate("  BLUE ") == "blue"
	assert aspect.validate("blue") == "blue"


def test_validate_rechaza_fuera_de_paleta_y_lista_las_validas():
	with pytest.raises(ValueError) as exc:
		aspect.validate("chartreuse")
	mensaje = str(exc.value)
	assert "chartreuse" in mensaje
	assert "blue" in mensaje and "emerald" in mensaje


def test_paleta_ilegible_degrada_a_vacio(monkeypatch):
	aspect.palette.cache_clear()
	monkeypatch.setattr(aspect, "PALETTE_FILE", "no_existe.yaml")
	try:
		assert aspect.palette() == {}
		with pytest.raises(ValueError):
			aspect.validate("blue")
	finally:
		aspect.palette.cache_clear()


def test_t1_el_declarado_gana_al_calculado(estado):
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	assert identity.get_hedonic_set_point() == "blue"


def test_t7_sin_aspecto_la_salida_es_la_de_antes(estado):
	_escribir_identidad(estado, HEDONIC_SET_POINT_COLOR="emerald", DEFAULT_EMOTION="neutral")
	assert identity.get_hedonic_set_point() == "emerald"
	assert identity.get_emergent_set_point() == "emerald"
	assert identity.get_aspect() is None


def test_t3_el_aspecto_no_es_fuente_de_conducta(estado):
	"""La voz lee el emergente: un aspecto azul no pinta el tono de azul (D-04)."""
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	assert identity.get_hedonic_set_point() == "blue"
	assert identity.get_emergent_set_point() == "gray"


def test_t3_sin_evidencia_el_tono_no_toma_el_color_del_aspecto(estado, monkeypatch):
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	monkeypatch.setattr(ToneAnalyzer, "_scroll_collection", staticmethod(lambda *a, **k: []))
	assert ToneAnalyzer.get_dominant_mood() == "gray"


def test_t2_el_sueno_no_pisa_la_declaracion(estado):
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	identity.update_identity("gray", "neutral")
	datos = json.loads((estado / "identity.json").read_text(encoding="utf-8"))
	assert datos["ASPECT"]["color"] == "blue"
	assert datos["HEDONIC_SET_POINT_COLOR"] == "gray"
	assert datos["EMERGENT_SET_POINT_COLOR"] == "gray"


def test_aspecto_malformado_degrada_a_ninguno(estado):
	_escribir_identidad(estado, ASPECT={"name": "sin color"})
	assert identity.get_aspect() is None
	assert identity.get_hedonic_set_point() == "gray"


def test_t2_el_ciclo_de_sueno_escribe_emergente_y_conserva_el_declarado(estado, monkeypatch):
	"""T2 por la ruta real: la fase de evolución calcula gris y no toca el azul declarado."""
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	monkeypatch.setattr(evolution.cfg, "DYNAMIC_EMOTION_SYNC", True)
	memorias = [_Point(color="gray", emotion="neutral", intensity=1.0)]

	color, _emotion = evolution.IdentityEvaluator.evaluate_set_point(manager=_Manager(memorias))

	assert color == "gray", "el método mide: devuelve lo calculado, no la declaración"
	assert identity.get_hedonic_set_point() == "blue", "el reposo que se reporta sigue siendo el declarado"
	datos = json.loads((estado / "identity.json").read_text(encoding="utf-8"))
	assert datos["EMERGENT_SET_POINT_COLOR"] == "gray"
	assert datos["HEDONIC_SET_POINT_COLOR"] == "gray"
	assert datos["ASPECT"]["color"] == "blue"


def test_t7_sin_aspecto_el_sueno_sigue_escribiendo_la_clave_legacy(estado, monkeypatch):
	_escribir_identidad(estado, HEDONIC_SET_POINT_COLOR="gray")
	monkeypatch.setattr(evolution.cfg, "DYNAMIC_EMOTION_SYNC", True)
	memorias = [_Point(color="yellow", emotion="good", intensity=1.0)]

	color, _emotion = evolution.IdentityEvaluator.evaluate_set_point(manager=_Manager(memorias))

	assert color == "yellow"
	datos = json.loads((estado / "identity.json").read_text(encoding="utf-8"))
	assert datos["HEDONIC_SET_POINT_COLOR"] == "yellow"
	assert "EMERGENT_SET_POINT_COLOR" not in datos


# ───────────────────────── F3: separación de consumidores ─────────────────────────

def test_pinchazo_sync_state_no_devuelve_el_aspecto(estado, monkeypatch):
	"""F3: el estado que se lee como ánimo no puede ser el color declarado (D-04)."""
	_escribir_identidad(estado, ASPECT={"color": "blue", "name": "attention", "why": "x"}, HEDONIC_SET_POINT_COLOR="gray")
	monkeypatch.setattr(tone_analyzer.cfg, "AFFECT_FROM_QUEUE", False)
	monkeypatch.setattr(tone_analyzer.cfg, "DYNAMIC_EMOTION_SYNC", True)
	monkeypatch.setattr(ToneAnalyzer, "_scroll_collection", staticmethod(lambda *a, **k: []))
	monkeypatch.setattr("red_pill.core.declared_mood.enabled", lambda: False)

	estado_voz = tone_analyzer.get_current_sync_state()

	assert estado_voz["mood"] == "gray", "la voz lee el emergente, no el aspecto"
	assert estado_voz["directive"] == CHROMA_TONE_MAPPING["gray"]
	assert identity.get_hedonic_set_point() == "blue", "y el reposo sigue siendo el declarado"


def test_tone_analyzer_no_importa_el_set_point_declarado():
	"""Guardia de importación: la fuga de conducta no da error, solo cambia el tono."""
	fuente = __import__("inspect").getsource(tone_analyzer)
	assert "get_hedonic_set_point" not in fuente
	assert "get_emergent_set_point" in fuente
