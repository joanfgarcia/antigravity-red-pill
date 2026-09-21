"""M4 single-writer — hub synthesis sobre engramas existentes (D2/D7/D14/G20)."""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.metabolism.hub_synthesis import group_by_session, hub_input_hash, hub_point_id, synthesize_session_hubs


class FakeClient:
	def __init__(self, points):
		self._points = points  # [(id, payload)]
		self.written: dict = {}
		self.marked: dict = {}

	def collection_exists(self, c):
		return c == "work_memories"

	def scroll(self, c, limit=1000, offset=None, with_payload=True, with_vectors=False):
		return [SimpleNamespace(id=i, payload=p) for i, p in self._points], None

	def retrieve(self, collection_name, ids):
		out = []
		for i in ids:
			if i in self.written:
				out.append(SimpleNamespace(id=i, payload=self.written[i]))
		return out

	def set_payload(self, collection_name, payload, points):
		self.marked.setdefault(collection_name, {}).update({p: payload for p in points})


class FakeMM:
	def __init__(self, client):
		self.client = client
		self.added: list = []

	def add_memory(self, **kw):
		self.added.append(kw)
		self.client.written[kw["point_id"]] = kw.get("metadata") or {}
		return kw["point_id"]


def _member(sid, content, cid="m1"):
	return (cid, {"origin": "memento", "node_type": "memento_engram", "session_id": sid, "content": content, "created_at": 100.0})


def test_hub_point_id_determinista():
	assert hub_point_id("work_memories", "opencode:ses_a") == hub_point_id("work_memories", "opencode:ses_a")
	assert hub_point_id("work_memories", "opencode:ses_a") != hub_point_id("social_memories", "opencode:ses_a")


def test_hub_input_hash_cambia_con_miembros():
	assert hub_input_hash(["a", "b"]) == hub_input_hash(["b", "a"])
	assert hub_input_hash(["a", "b"]) != hub_input_hash(["a", "c"])


def test_group_excluye_hubs_y_sin_sesion():
	points = [
		_member("opencode:ses_a", "idea 1", "m1"),
		_member("opencode:ses_a", "idea 2", "m2"),
		("h", {"node_type": "synthesis_hub", "session_id": "opencode:ses_a"}),
		("x", {"origin": "memento", "content": "sin sesión"}),
	]
	groups = group_by_session(points)
	assert set(groups) == {"opencode:ses_a"}
	assert len(groups["opencode:ses_a"]) == 2


def test_hubs_flag_off_no_hace_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", False, raising=False)
	mm = FakeMM(FakeClient([_member("opencode:ses_a", "idea")]))
	stats = synthesize_session_hubs(mm, collections=("work_memories",))
	assert stats["enabled"] is False and not mm.added


def test_hubs_escribe_marca_e_idempotente(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("opencode:ses_a", "idea 1", "m1"), _member("opencode:ses_a", "idea 2", "m2")])
	mm = FakeMM(client)

	def synthesizer(chunks):
		return {"title": "T", "summary": "S", "texture": {"theme": "t"}, "lang": "es"}

	def affect(chunks):
		return ("gray", 0.5)

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=synthesizer, affect_fn=affect)
	assert stats["hubs_written"] == 1
	hid = hub_point_id("work_memories", "opencode:ses_a")
	assert mm.added[0]["point_id"] == hid
	assert mm.added[0]["metadata"]["node_type"] == "synthesis_hub"
	assert mm.added[0]["metadata"]["lazarus_phase"] == "synthesis_hub"
	assert set(client.marked["work_memories"]) == {"m1", "m2"}
	assert client.marked["work_memories"]["m1"]["hubbed"] is True

	# Segunda pasada: mismo input → se salta (idempotente, sin LLM).
	mm2 = FakeMM(client)
	stats2 = synthesize_session_hubs(mm2, collections=("work_memories",), synthesizer=synthesizer, affect_fn=affect)
	assert stats2["hubs_skipped"] == 1 and not mm2.added
