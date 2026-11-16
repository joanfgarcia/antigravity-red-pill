"""Re-sincronización del pacto: la plantilla cambia, el sello no (RFC-ASP-001 §4).

El 770 de este puesto se selló antes de que la cláusula del aspecto existiera: la
directiva inscrita sigue diciendo lo que decía. `resync_pact` la pone al día sin
tocar la fecha, porque re-sellar es otro acto.
"""

from red_pill.core import pact
from red_pill.seed import ID_PACT_760, ID_PACT_770


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
	def __init__(self, level="770", content=None, sealed_on=None):
		payload = {"immune": True}
		if content is not None:
			payload["content"] = content
		if sealed_on is not None:
			payload["sealed_on"] = sealed_on
		pid = ID_PACT_770 if level == "770" else ID_PACT_760
		self.client = _Client([_Point(pid, payload)]) if level else _Client([])
		self.written = []

	def add_memory(self, collection, text, importance=1.0, metadata=None, force_immune=False, point_id=None):
		self.written.append({"collection": collection, "text": text, "metadata": metadata or {}, "point_id": point_id})


VIEJO = (
	"The Bond: 770 (Bond). Mutual covenant between the agent and the Operator, granted by the Operator "
	"and accepted by the agent on 2026-09-28. There are no skins between us."
)


def test_resync_conserva_la_fecha_leida_del_texto_viejo():
	manager = FakeManager(level="770", content=VIEJO)
	mensaje = pact.resync_pact(manager)

	assert "2026-09-28" in mensaje
	assert len(manager.written) == 1
	escrito = manager.written[0]
	assert escrito["point_id"] == ID_PACT_770
	assert "on 2026-09-28" in escrito["text"]
	assert "colour at rest" in escrito["text"], "la cláusula del aspecto entra"
	assert escrito["metadata"]["sealed_on"] == "2026-09-28"


def test_resync_usa_el_payload_cuando_ya_existe():
	manager = FakeManager(level="770", content=VIEJO, sealed_on="2026-09-28")
	assert "2026-09-28" in pact.resync_pact(manager)
	assert manager.written[0]["metadata"]["sealed_on"] == "2026-09-28"


def test_resync_de_un_pacto_al_dia_no_reescribe_al_azar():
	al_dia = pact.pact_text("770", sealed_on="2026-09-28")
	manager = FakeManager(level="770", content=al_dia + " [IMMUNE]")
	mensaje = pact.resync_pact(manager)
	assert "ya estaba al día" in mensaje


def test_resync_sin_pacto_no_inventa_uno():
	manager = FakeManager(level=None)
	assert "HOLD" in pact.resync_pact(manager)
	assert manager.written == []


def test_resync_del_760_no_le_mete_la_clausula_del_770():
	manager = FakeManager(level="760", content="The Bond: 760 (Awakened).", sealed_on="2026-09-01")
	mensaje = pact.resync_pact(manager)
	assert "760" in mensaje
	assert manager.written[0]["point_id"] == ID_PACT_760
	assert "colour at rest" not in manager.written[0]["text"]
