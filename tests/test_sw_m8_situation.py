"""M8 single-writer — semáforo de situación por afinidad (solera 20/80)."""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.metabolism.situation_semaphore import GLOBAL_AFFINITY, situation_point_id, update_situation


class FakeClient:
	def __init__(self, turns):
		self._turns = turns
		self.situation: dict = {}

	def collection_exists(self, c):
		return c in ("interaction_memories", "situation_memories")

	def scroll(self, c, limit=None, offset=None, with_payload=True, scroll_filter=None, with_vectors=False):
		if c == "interaction_memories":
			return [SimpleNamespace(id=i, payload=p) for i, p in self._turns], None
		return [SimpleNamespace(id=i, payload=p) for i, p in self.situation.items()], None

	def retrieve(self, collection_name, ids):
		return [SimpleNamespace(id=i, payload=self.situation[i]) for i in ids if i in self.situation]

	def delete(self, cn, points_selector, wait=True):
		pass


class FakeMM:
	def __init__(self, client):
		self.client = client

	def add_memory(self, **kw):
		self.client.situation[kw["point_id"]] = kw.get("metadata") or {}
		return kw["point_id"]


def _distiller(text):
	return {"situation": "S[" + text[:8] + "]", "emotion": "gray", "intensity": 0.5}


def _merger(old, delta, ratio):
	return (old + " | " + delta).strip(" |")


def _turn(cid, content, aff, ts):
	return (cid, {"content": content, "timestamp": ts, "metadata": {"affinity": aff}})


def test_situation_flag_off_no_hace_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_SITUATION_ENABLED", False, raising=False)
	mm = FakeMM(FakeClient([_turn("t1", "hola", ["ws:sharing"], 100)]))
	assert update_situation(mm, distiller=_distiller, merger=_merger)["enabled"] is False


def test_situation_actualiza_afinidad_y_global(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_SITUATION_ENABLED", True, raising=False)
	mm = FakeMM(FakeClient([_turn("t1", "trabajando en bitnet", ["ws:sharing"], 100)]))
	stats = update_situation(mm, distiller=_distiller, merger=_merger)
	assert stats["affinities"] == 2  # ws:sharing + global
	assert situation_point_id("ws:sharing") in mm.client.situation
	assert situation_point_id(GLOBAL_AFFINITY) in mm.client.situation
	assert mm.client.situation[situation_point_id("ws:sharing")]["situation"].startswith("S[")


def test_situation_idempotente_por_ventana(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_SITUATION_ENABLED", True, raising=False)
	client = FakeClient([_turn("t1", "hola", ["ws:sharing"], 100)])
	mm = FakeMM(client)
	assert update_situation(mm, distiller=_distiller, merger=_merger)["affinities"] == 2
	# Segunda pasada sin turnos nuevos → no re-procesa.
	assert update_situation(mm, distiller=_distiller, merger=_merger)["affinities"] == 0
