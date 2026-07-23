"""T2+P2: HUB-v2 synthesis, affect derivation from history, relic transport."""

import json
from unittest.mock import MagicMock

from red_pill.metabolism.distiller import (
	HUB_TEXTURE_MAX_CHARS,
	build_emotional_vector,
	derive_hub_affect,
	merge_relics,
	synthesize_hub_v2,
)

CHUNKS = [
	{"summary": "s1", "texture": "cálido", "emotion": "joy", "intensity": 0.85, "category": "social", "lang": "es", "relics": ["cita uno"]},
	{
		"summary": "s2",
		"texture": "técnico",
		"emotion": "neutral",
		"intensity": 0.3,
		"category": "work",
		"lang": "es",
		"relics": ["cita dos", "cita uno"],
	},
	{"summary": "s3", "texture": "", "emotion": "neutral", "intensity": 0.3, "category": "social", "lang": "es", "relics": []},
]


def _mock_provider(monkeypatch, payload):
	from red_pill.core import providers

	provider = MagicMock()
	provider.generate.return_value = json.dumps(payload) if isinstance(payload, dict) else payload
	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))
	return provider


def test_derive_hub_affect_dominant_not_last():
	# Legacy took the LAST chunk's emotion (neutral); history-weighted must keep joy
	# only if its cumulative intensity wins — here neutral wins 0.6 vs 0.85 joy... joy wins.
	emotion, intensity = derive_hub_affect(CHUNKS)
	assert emotion == "joy"  # 0.85 joy > 0.6 accumulated neutral
	assert intensity == 0.85


def test_derive_hub_affect_accumulation_beats_single_peak():
	chunks = [
		{"emotion": "neutral", "intensity": 0.5},
		{"emotion": "neutral", "intensity": 0.5},
		{"emotion": "joy", "intensity": 0.7},
	]
	emotion, _ = derive_hub_affect(chunks)
	assert emotion == "neutral"  # 1.0 accumulated > 0.7


def test_merge_relics_dedupe_and_cap():
	assert merge_relics(CHUNKS) == ["cita uno", "cita dos"]
	many = [{"relics": [f"r{i}"]} for i in range(9)]
	assert len(merge_relics(many)) == 5


def test_build_emotional_vector_shape():
	affects = [{"child_id": "a", "emotion": "joy", "intensity": 0.8, "category": "social"}]
	assert build_emotional_vector(affects) == {"fragments": affects}


def test_synthesize_hub_v2_happy_path(monkeypatch):
	_mock_provider(monkeypatch, {"title": "Sesión definitiva", "summary": "Resumen maestro.", "texture": "Alivio tangible.", "lang": "es"})
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["title"] == "Sesión definitiva"
	assert hub["texture"] == "Alivio tangible."
	assert hub["lang"] == "es"
	assert "_is_fallback" not in hub


def test_synthesize_hub_v2_truncates_concatenated_texture(monkeypatch):
	_mock_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "x" * 2000, "lang": "es"})
	hub = synthesize_hub_v2(CHUNKS)
	assert len(hub["texture"]) == HUB_TEXTURE_MAX_CHARS


def test_synthesize_hub_v2_falls_back_on_garbage(monkeypatch):
	_mock_provider(monkeypatch, "not json at all")
	monkeypatch.setattr("red_pill.metabolism.distiller.synthesize_hub", lambda summaries: "s1 s2 s3")
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["texture"] == ""
	assert hub["summary"]  # legacy aggregation still yields a hub
