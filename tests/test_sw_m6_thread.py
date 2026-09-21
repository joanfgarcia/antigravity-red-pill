"""M6 single-writer — micro-hilo de Ariadna (prev/next_member por sesión)."""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.metabolism.thread_synthesis import member_sort_key, weave_member_threads


class FakeClient:
	def __init__(self, points):
		self._points = points
		self.payloads: dict = {}

	def collection_exists(self, c):
		return c == "work_memories"

	def scroll(self, c, limit=1000, offset=None, with_payload=True, with_vectors=False):
		return [SimpleNamespace(id=i, payload=p) for i, p in self._points], None

	def set_payload(self, collection_name, payload, points):
		for p in points:
			self.payloads.setdefault(str(p), {}).update(payload)


class FakeMM:
	def __init__(self, client):
		self.client = client


def _m(sid, ref, cid):
	return (cid, {"origin": "memento", "session_id": sid, "refine_ref": ref})


def test_member_sort_key_por_numero_de_refine():
	k1 = member_sort_key({"refine_ref": "2026-09/opencode/s/refine/017-x.md"})
	k2 = member_sort_key({"refine_ref": "2026-09/opencode/s/refine/002-y.md"})
	assert k2 < k1


def test_thread_flag_off_no_hace_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_THREAD_ENABLED", False, raising=False)
	client = FakeClient([_m("s", "…/001-a.md", "m1"), _m("s", "…/002-b.md", "m2")])
	stats = weave_member_threads(FakeMM(client), collections=("work_memories",))
	assert stats["enabled"] is False and not client.payloads


def test_thread_encadena_por_orden_de_refine(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_THREAD_ENABLED", True, raising=False)
	client = FakeClient([_m("s", "…/017-late.md", "m17"), _m("s", "…/002-early.md", "m2")])
	stats = weave_member_threads(FakeMM(client), collections=("work_memories",))
	assert stats["sessions"] == 1
	assert client.payloads["m2"]["member_index"] == 0
	assert client.payloads["m2"]["next_member"] == "m17"
	assert client.payloads["m17"]["prev_member"] == "m2"
	assert client.payloads["m17"]["member_index"] == 1
	assert client.payloads["m17"]["member_count"] == 2


def test_order_members_por_index_con_fallback():
	from red_pill.metabolism.thread_synthesis import order_members

	entries = [
		("b", {"member_index": 2, "refine_ref": "…/009-b.md"}),
		("a", {"member_index": 1, "refine_ref": "…/003-a.md"}),
		("c", {"refine_ref": "…/002-c.md"}),  # sin index → al final
	]
	assert [mid for mid, _ in order_members(entries)] == ["a", "b", "c"]
