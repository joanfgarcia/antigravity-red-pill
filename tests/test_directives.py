"""Directivas: filtro de vigencia por `superseded` (read_core_directives)."""

from __future__ import annotations

from red_pill.core.directives import active_directive_contents, is_active, mark_superseded


class _P:
	def __init__(self, payload):
		self.payload = payload


class _Client:
	def __init__(self):
		self.calls = []

	def set_payload(self, collection_name, payload, points):
		self.calls.append({"collection": collection_name, "payload": payload, "points": points})


class _MM:
	def __init__(self):
		self.client = _Client()


def test_is_active_default_y_sentinelas():
	assert is_active({}) is True
	assert is_active(None) is True
	assert is_active({"superseded": None}) is True
	assert is_active({"superseded": ""}) is True
	assert is_active({"superseded": "null"}) is True


def test_is_active_si_reemplazada():
	assert is_active({"superseded": "00000000-0000-0000-0000-000000000070"}) is False


def test_active_directive_contents_filtra():
	points = [
		_P({"content": "vieja 760", "immune": True, "superseded": "id-770"}),
		_P({"content": "nueva 770", "immune": True}),
		_P({"content": "no inmune", "immune": False}),
		_P({"content": "activa 2", "immune": True, "superseded": None}),
		_P(None),
	]
	out = active_directive_contents(points)
	assert out == ["nueva 770", "activa 2"]


def test_mark_superseded_escribe_payload():
	mm = _MM()
	assert mark_superseded(mm, "old-id", "new-id") is True
	c = mm.client.calls[0]
	assert c["collection"] == "directive_memories"
	assert c["payload"] == {"superseded": "new-id"}
	assert c["points"] == ["old-id"]


def test_mark_superseded_no_lanza_si_falla():
	class _Boom(_MM):
		def __init__(self):
			self.client = type("C", (), {"set_payload": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))})()

	assert mark_superseded(_Boom(), "o", "n") is False
