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
			("c1", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
			("c2", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
			("c3", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
			("h1", {"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub"}),
			("m1", {"node_type": "memento_engram", "origin": "memento", "session_id": "s", "hubbed": True}),
			("m2", {"node_type": "memento_engram", "origin": "memento", "session_id": "s", "hubbed": True}),
		],
		"situation_memories": [("s1", {"updated_at": now - 3600})],
		"interaction_memories": [
			("i1", {"metadata": {"affinity": ["ws:x"]}}),
			("i2", {"metadata": {}}),
		],
	}
	h = compute_sw_health(FakeMM(FakeClient(data)))
	wm = h["collections"]["work_memories"]
	assert wm["hubs"] == 1
	assert wm["content"] == 5  # incluye los miembros hubbed
	assert wm["hubbed_members"] == 2
	# Cobertura real (hubbed/content) ≠ densidad de hubs (hubs/content).
	assert wm["hub_coverage_pct"] == 40.0
	assert wm["hub_ratio_pct"] == 20.0
	assert h["solera_age_h"] == 1.0
	assert h["affinity_coverage"] == 0.5


def test_coverage_uses_the_synthesis_content_predicate():
	"""Legacy sin node_type cuenta como contenido (igual que hub_synthesis) y un
	`hubbed` fuera del contenido no infla el numerador: cobertura <= 100%."""
	data = {
		"work_memories": [
			("l1", {"session_id": "s", "hubbed": True}),  # legacy sin node_type: contenido para la síntesis
			("l2", {"session_id": "s", "hubbed": True}),
			("x1", {"node_type": "otro", "hubbed": True}),  # no es contenido
			("h1", {"node_type": "synthesis_hub", "hubbed": True}),  # hub: nunca contenido
		],
	}
	wm = compute_sw_health(FakeMM(FakeClient(data)))["collections"]["work_memories"]
	assert wm["content"] == 2
	assert wm["hubbed_members"] == 2
	assert wm["hub_coverage_pct"] == 100.0
	assert wm["hub_coverage_pct"] <= 100.0


def test_empty_collection_coverage_is_na():
	"""Sin contenido no hay cobertura que medir: None ("n/a"), no un 0% falso."""
	data = {"work_memories": [("h1", {"node_type": "synthesis_hub"})], "social_memories": []}
	cols = compute_sw_health(FakeMM(FakeClient(data)))["collections"]
	for c in ("work_memories", "social_memories"):
		assert cols[c]["content"] == 0
		assert cols[c]["hub_coverage_pct"] is None
		assert cols[c]["hub_ratio_pct"] is None


class _SignalMM(FakeMM):
	def __init__(self, client):
		super().__init__(client)
		self.signals = []

	def inject_signal(self, **kw):
		self.signals.append(kw)


def _run_plugin(monkeypatch, data):
	import asyncio
	from unittest.mock import MagicMock

	import red_pill.config as cfg
	from red_pill.swarm.agents.janitor_plugins.sw_observability import SwObservabilityPlugin

	monkeypatch.setattr(cfg, "SW_HUBS_ENABLED", True, raising=False)
	mm = _SignalMM(FakeClient(data))
	asyncio.run(SwObservabilityPlugin().execute(MagicMock(), {}, memory_manager=mm))
	return {s["name"] for s in mm.signals}


def test_plugin_no_pain_on_empty_collection(monkeypatch):
	names = _run_plugin(monkeypatch, {"work_memories": [], "situation_memories": [("s1", {"updated_at": time.time()})]})
	assert "sw_hub_coverage" in names
	assert "sw_hub_coverage_low" not in names


def test_plugin_pain_below_threshold(monkeypatch):
	"""El dolor real (<50%) se mantiene."""
	data = {
		"work_memories": [
			("c1", {"node_type": "memento_engram", "session_id": "s"}),
			("c2", {"node_type": "memento_engram", "session_id": "s"}),
			("c3", {"node_type": "memento_engram", "session_id": "s", "hubbed": True}),
		],
	}
	assert "sw_hub_coverage_low" in _run_plugin(monkeypatch, data)


def test_coverage_ignores_content_the_synthesis_can_never_group():
	"""Un legacy sin `session_id` es contenido pero nunca entrará en un hub: no
	cuenta en el denominador (si contara, 10 legacy hundirían la cobertura al 16.7%)."""
	data = {
		"work_memories": [(f"l{i}", {}) for i in range(10)]
		+ [
			("m1", {"node_type": "memento_engram", "session_id": "s", "hubbed": True}),
			("m2", {"node_type": "memento_engram", "session_id": "s", "hubbed": True}),
		],
	}
	wm = compute_sw_health(FakeMM(FakeClient(data)))["collections"]["work_memories"]
	assert wm["content"] == 12
	assert wm["groupable"] == 2
	assert wm["hub_coverage_pct"] == 100.0

