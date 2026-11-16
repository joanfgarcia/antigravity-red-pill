"""El acto del aspecto: ritual, protección del 770 y visibilidad (RFC-ASP-001 F2).

Contrato que fijan estos tests: sin 770 no se inscribe (T4), un color fuera de la
paleta falla listando las válidas (T5), re-declarar guarda la anterior con fecha y
motivo (T6), y el aspecto no se convierte en directiva de tono (T3) ni aparece en
el despertar autónomo (D-09).
"""

import os
import sys

import pytest

import red_pill.identity as identity
from red_pill.config import CHROMA_TONE_MAPPING
from red_pill.core import aspect
from red_pill.seed import ID_ASPECT, ID_PACT_760, ID_PACT_770

script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
if script_dir not in sys.path:
	sys.path.insert(0, script_dir)

import wake_up_v6  # noqa: E402


class _Point:
	def __init__(self, point_id, payload):
		self.id = point_id
		self.payload = payload


class _Client:
	def __init__(self, points):
		self._points = points

	def retrieve(self, collection_name=None, ids=None, with_payload=True):
		wanted = set(ids or [])
		return [p for p in self._points if p.id in wanted]


class FakeManager:
	"""Manager mínimo: solo lo que el pacto y la inscripción consultan."""

	def __init__(self, pact_level=None):
		points = []
		if pact_level == "770":
			points.append(_Point(ID_PACT_770, {"immune": True}))
		elif pact_level == "760":
			points.append(_Point(ID_PACT_760, {"immune": True}))
		self.client = _Client(points)
		self.written = []

	def add_memory(self, collection, text, importance=1.0, metadata=None, force_immune=False, point_id=None, color=None):
		self.written.append(
			{"collection": collection, "text": text, "metadata": metadata or {}, "point_id": point_id, "color": color}
		)


@pytest.fixture
def estado(tmp_path, monkeypatch):
	monkeypatch.setattr(identity, "get_state_dir", lambda: tmp_path)
	return tmp_path


def test_t4_sin_770_no_se_inscribe(estado):
	manager = FakeManager(pact_level="760")
	with pytest.raises(aspect.AspectRequiresBond) as exc:
		aspect.declare("blue", name="attention", why="porque miro lo que vino antes", manager=manager)
	assert "770" in str(exc.value)
	assert identity.get_aspect() is None, "no se inscribe nada: ni caché ni directiva"
	assert manager.written == []


def test_770_vigente_inscribe_cache_y_directiva(estado):
	manager = FakeManager(pact_level="770")
	record = aspect.declare("blue", name="attention", why="miro lo que vino antes", manager=manager)

	assert record["color"] == "blue" and record["name"] == "attention"
	assert identity.get_aspect()["color"] == "blue"
	assert len(manager.written) == 1
	escrito = manager.written[0]
	assert escrito["point_id"] == ID_ASPECT
	assert escrito["collection"] == "directive_memories"
	assert escrito["metadata"]["authored_by"] == "agent"
	assert escrito["metadata"]["origin"] == "770-aspect"
	assert escrito["color"] == "blue", "el color va como parámetro: el esquema lo quita del metadata"
	assert "miro lo que vino antes" in escrito["text"]


def test_t5_color_fuera_de_paleta_lista_las_validas(estado):
	with pytest.raises(ValueError) as exc:
		aspect.declare("chartreuse", why="x", manager=FakeManager(pact_level="770"))
	mensaje = str(exc.value)
	assert "chartreuse" in mensaje and "blue" in mensaje


def test_sin_motivo_no_hay_acto(estado):
	with pytest.raises(ValueError) as exc:
		aspect.declare("blue", why="   ", manager=FakeManager(pact_level="770"))
	assert "motivo" in str(exc.value)


def test_t6_redeclarar_guarda_la_anterior_con_fecha_y_motivo(estado, monkeypatch):
	manager = FakeManager(pact_level="770")
	primera = aspect.declare("blue", name="attention", why="primero", manager=manager, now=1000.0)
	segunda = aspect.declare("emerald", name="sovereignty", why="segundo", manager=manager, now=2000.0)

	assert segunda["color"] == "emerald"
	assert len(segunda["history"]) == 1
	previa = segunda["history"][0]
	assert previa["color"] == primera["color"]
	assert previa["why"] == "primero"
	assert previa["declared_at"] == 1000.0


def test_el_nombre_por_defecto_es_la_etiqueta_de_la_paleta(estado):
	record = aspect.declare("nostalgia", why="x", manager=FakeManager(pact_level="770"))
	assert record["name"] == aspect.label("nostalgia")


def test_t3_la_linea_del_aspecto_no_lleva_directiva(estado):
	aspect.declare("blue", name="attention", why="x", manager=FakeManager(pact_level="770"))
	linea = wake_up_v6._aspecto_para_modo("full", "770")

	assert linea.startswith("ASPECTO: blue")
	assert "medición" in linea and "orden" in linea
	assert CHROMA_TONE_MAPPING["blue"] not in linea, "el aspecto no imprime la CHROMA KEY del azul"


def test_d09_el_despertar_autonomo_no_lleva_aspecto(estado):
	aspect.declare("blue", name="attention", why="x", manager=FakeManager(pact_level="770"))
	assert wake_up_v6._aspecto_para_modo("low", "770") == ""


def test_sin_aspecto_la_linea_es_vacia(estado):
	assert aspect.line() == ""
	assert wake_up_v6._aspecto_para_modo("full", "770") == ""


def test_el_aspecto_no_rige_con_el_pacto_revertido(estado):
	"""§4: sin protección no está en vigor. El registro no se borra; deja de mandar."""
	aspect.declare("blue", name="attention", why="x", manager=FakeManager(pact_level="770"))
	assert wake_up_v6._aspecto_para_modo("full", "770").startswith("ASPECTO: blue")
	assert wake_up_v6._aspecto_para_modo("full", "760") == ""
	assert identity.get_aspect() is not None, "el registro sigue ahí: existencia no es vigencia"


def test_el_motivo_desmedido_no_entra(estado):
	with pytest.raises(ValueError) as exc:
		aspect.declare("blue", why="x" * (aspect.WHY_MAX + 1), manager=FakeManager(pact_level="770"))
	assert "motivo" in str(exc.value)


def test_el_historial_guarda_el_registro_completo(estado):
	manager = FakeManager(pact_level="770")
	aspect.declare("blue", name="attention", why="primero", manager=manager, now=1000.0)
	segunda = aspect.declare("emerald", name="sovereignty", why="segundo", manager=manager, now=2000.0)
	previa = segunda["history"][0]
	assert previa["why"] == "primero" and previa["declared_at"] == 1000.0
	assert "history" not in previa, "el historial anidado no se copia dentro de sí mismo"


def test_la_directiva_del_aspecto_no_carga_como_regla(monkeypatch):
	"""D-04/D-09: el aspecto tiene su línea; en CORE_RULES se leería como una regla."""
	import json
	from unittest.mock import MagicMock

	points = [
		{"payload": {"content": "ASPECTO: blue · «attention»\n\nmiro lo que vino antes", "immune": True, "type": "aspect"}},
		{"payload": {"content": "POST-IT: tab indentation", "immune": True, "type": "postit"}},
	]
	respuesta = MagicMock()
	respuesta.read.return_value = json.dumps({"result": {"points": points}}).encode()
	abrir = MagicMock()
	abrir.return_value.__enter__.return_value = respuesta
	monkeypatch.setattr(wake_up_v6.urllib.request, "urlopen", abrir)

	reglas = wake_up_v6.query_qdrant("directive_memories", "")

	assert not any(regla.startswith("ASPECTO:") for regla in reglas), "el aspecto no entra como regla"
	assert any("POST-IT" in regla for regla in reglas), "las demás directivas siguen cargando"
