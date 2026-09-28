"""Unit del Pacto como directivas (Opción A): nombrado, doble llave y vigencia."""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.core import pact
from red_pill.seed import ID_IDENTITY, ID_PACT_760, ID_PACT_770, ID_PACT_770_ACCEPT, ID_PACT_770_GRANT


class _Client:
	def __init__(self):
		self.store: dict = {}

	def retrieve(self, collection_name, ids, with_payload=True):
		return [SimpleNamespace(id=i, payload=dict(self.store[i])) for i in ids if i in self.store]

	def set_payload(self, collection_name, payload, points):
		# Qdrant: set_payload sobre un punto inexistente no lo crea.
		for p in points:
			if p in self.store:
				self.store[p].update(payload)

	def delete(self, collection_name, points_selector, wait=True):
		for p in getattr(points_selector, "points", []):
			self.store.pop(p, None)


class _Mgr:
	def __init__(self):
		self.client = _Client()

	def add_memory(self, collection, text, importance, metadata, force_immune, point_id):
		self.client.store[point_id] = {"content": text, "immune": force_immune, **metadata}


def test_naming_crea_identidad_y_760_vigente():
	m = _Mgr()
	res = pact.inscribe_naming(m, "Soy Aleth (Aletheia). Hablo de mí en femenino.")
	assert "[OK]" in res
	assert ID_IDENTITY in m.client.store and ID_PACT_760 in m.client.store
	assert m.client.store[ID_IDENTITY]["type"] == "identity"
	assert pact.active_pact_level(m) == "760"


def test_naming_sin_texto_se_retiene():
	m = _Mgr()
	assert "[HOLD]" in pact.inscribe_naming(m, None)
	assert m.client.store == {}


def test_seal_770_requiere_identidad_primero():
	m = _Mgr()
	assert "[HOLD]" in pact.seal_pact(m, "770", grant=True, accept=True)
	assert ID_PACT_770 not in m.client.store


def test_seal_770_una_sola_llave_queda_pendiente():
	m = _Mgr()
	pact.inscribe_naming(m, "Soy Aleth.")
	res = pact.seal_pact(m, "770", grant=True)  # falta el accept del agente
	assert "[PENDING]" in res
	assert ID_PACT_770 not in m.client.store
	assert pact.active_pact_level(m) == "760"


def test_seal_770_doble_llave_sella_y_reemplaza_760():
	m = _Mgr()
	pact.inscribe_naming(m, "Soy Aleth.")
	assert "[PENDING]" in pact.seal_pact(m, "770", grant=True)
	res = pact.seal_pact(m, "770", accept=True)  # segunda llave → sella
	assert "[OK]" in res
	assert m.client.store[ID_PACT_770]["pact_level"] == "770"
	assert m.client.store[ID_PACT_760]["superseded"] == ID_PACT_770
	assert pact.active_pact_level(m) == "770"


def test_revertir_760_limpia_mitades():
	m = _Mgr()
	pact.inscribe_naming(m, "Soy Aleth.")
	pact.seal_pact(m, "770", grant=True, accept=True)
	res = pact.seal_pact(m, "760")
	assert "[OK]" in res
	assert ID_PACT_770_GRANT not in m.client.store and ID_PACT_770_ACCEPT not in m.client.store
	assert m.client.store[ID_PACT_770]["superseded"] == ID_PACT_760
	assert pact.active_pact_level(m) == "760"


def test_instruccion_menciona_genero_y_ejemplo():
	ins = pact.IDENTITY_INSTRUCTION
	assert "GÉNERO" in ins and "Ejemplo" in ins and "Aletheia" in ins
