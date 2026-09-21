"""M9 single-writer — olvido elegante de curados (eje propio + demote)."""

from __future__ import annotations

import time
from types import SimpleNamespace

from red_pill.metabolism.maintenance import erode_curated


class FakeClient:
	def __init__(self, points):
		self._points = points
		self.deleted: list = []

	def collection_exists(self, c):
		return c == "work_memories"

	def scroll(self, c, scroll_filter=None, limit=500, offset=None, with_payload=True, with_vectors=False):
		# Como Qdrant: solo devuelve los curados que el filtro `should` selecciona.
		curated = [
			(i, p)
			for i, p in self._points
			if p.get("node_type") in ("memento_engram", "synthesis_hub") or p.get("lazarus_phase") == "synthesis_hub"
		]
		return [SimpleNamespace(id=i, payload=p) for i, p in curated], None

	def delete(self, collection_name, points_selector, wait=True):
		ids = getattr(points_selector, "points", [])
		self.deleted.extend(str(x) for x in ids)


class FakeMM:
	def __init__(self, client):
		self.client = client


YEAR = 365 * 86400


def _c(sid, node_type="memento_engram", age_days=0, immune=False, cid="c"):
	ts = time.time() - age_days * 86400
	return (cid, {"node_type": node_type, "session_id": sid, "created_at": ts, "last_reinforced_at": ts, "immune": immune})


def test_demote_flag_off_no_hace_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_EROSION_DEMOTE_ENABLED", False, raising=False)
	client = FakeClient([_c("s", age_days=10 * 365)])
	stats = erode_curated(FakeMM(client), collections=("work_memories",))
	assert stats["enabled"] is False and not client.deleted


def test_demote_por_eje_propio(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_EROSION_DEMOTE_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "CURATED_MIN_LIFETIME_YEARS", 5.0, raising=False)
	client = FakeClient(
		[
			_c("s_old", age_days=6 * 365, cid="old"),
			_c("s_new", age_days=30, cid="new"),
			_c("s_hub", node_type="synthesis_hub", age_days=6 * 365, cid="hub"),
			_c("s_imm", age_days=6 * 365, immune=True, cid="imm"),
			("nc", {"node_type": "interactive_engram", "created_at": time.time() - 10 * 365 * 86400}),
		]
	)
	stats = erode_curated(FakeMM(client), collections=("work_memories",))
	assert set(client.deleted) == {"old", "hub"}  # viejos curados; inmune y no-curado se quedan
	assert stats["demoted"] == 2
