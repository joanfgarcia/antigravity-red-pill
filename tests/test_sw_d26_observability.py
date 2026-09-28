"""D26 single-writer — observabilidad (cobertura de hubs, frescura, afinidad)."""

from __future__ import annotations

import time
from types import SimpleNamespace

from red_pill.metabolism.sw_observability import compute_sw_health


class FakeClient:
	def __init__(self, data):
		self._data = data  # {collection: [(id, payload)]}

	def collection_exists(self, c):
		return c in self._data

	def scroll(self, c, limit=1000, offset=None, with_payload=True, with_vectors=False):
		return [SimpleNamespace(id=i, payload=p) for i, p in self._data.get(c, [])], None


class FakeMM:
	def __init__(self, client):
		self.client = client


def test_compute_sw_health():
	now = time.time()
	data = {
		"work_memories": [
			("c1", {"node_type": "memento_engram", "origin": "memento"}),
			("c2", {"node_type": "memento_engram", "origin": "memento"}),
			("c3", {"node_type": "memento_engram", "origin": "memento"}),
			("h1", {"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub"}),
			("m1", {"node_type": "memento_engram", "origin": "memento", "hubbed": True}),
		],
		"situation_memories": [("s1", {"updated_at": now - 3600})],
		"interaction_memories": [
			("i1", {"metadata": {"affinity": ["ws:x"]}}),
			("i2", {"metadata": {}}),
		],
	}
	h = compute_sw_health(FakeMM(FakeClient(data)))
	assert h["collections"]["work_memories"]["hubs"] == 1
	assert h["collections"]["work_memories"]["content"] == 4  # incluye el miembro hubbed
	assert h["collections"]["work_memories"]["hubbed_members"] == 1
	assert h["solera_age_h"] == 1.0
	assert h["affinity_coverage"] == 0.5
