"""T1: COGNITIVE_DISTILLER_V3 — mechanical validation of the distiller contract."""

import json
from unittest.mock import MagicMock

from red_pill.metabolism.distiller import VALID_EMOTIONS, _validate_relics, distill_engram

LONG_RAW = "Charla distendida sobre la caminata de ayer. " * 8  # > MIN_TEXTURE_CHARS


def _mock_provider(monkeypatch, payload: dict):
	from red_pill.core import providers

	provider = MagicMock()
	provider.generate.return_value = json.dumps(payload)
	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))
	return provider


def test_emotion_outside_taxonomy_normalizes_to_neutral(monkeypatch):
	_mock_provider(monkeypatch, {"summary": "s", "emotion": "enjoyment", "intensity": 0.7, "category": "social"})
	result = distill_engram(LONG_RAW)
	assert result["emotion"] == "neutral"


def test_valid_emotion_passes(monkeypatch):
	_mock_provider(monkeypatch, {"summary": "s", "emotion": "nostalgia", "intensity": 0.6, "category": "social"})
	assert distill_engram(LONG_RAW)["emotion"] == "nostalgia"


def test_intensity_clamped(monkeypatch):
	_mock_provider(monkeypatch, {"summary": "s", "emotion": "joy", "intensity": 1.7, "category": "social"})
	assert distill_engram(LONG_RAW)["intensity"] == 1.0


def test_invalid_category_falls_back(monkeypatch):
	_mock_provider(monkeypatch, {"summary": "s", "emotion": "joy", "intensity": 0.5, "category": "mixed"})
	assert distill_engram(LONG_RAW, fallback_category="work")["category"] == "work"


def test_texture_gate_short_fragment(monkeypatch):
	_mock_provider(
		monkeypatch,
		{"summary": "s", "emotion": "neutral", "intensity": 0.2, "category": "work", "texture": "Teatro inventado sobre 5 palabras."},
	)
	result = distill_engram("método o estrucura de datos...")  # 31 chars < MIN_TEXTURE_CHARS
	assert result["texture"] == ""


def test_texture_kept_on_long_fragment(monkeypatch):
	_mock_provider(
		monkeypatch,
		{"summary": "s", "emotion": "joy", "intensity": 0.8, "category": "social", "texture": "Ambiente cálido.", "lang": "es"},
	)
	result = distill_engram(LONG_RAW)
	assert result["texture"] == "Ambiente cálido."
	assert result["lang"] == "es"


def test_relics_literal_substring_kept_paraphrase_dropped():
	raw = "una charla que tubimos distendida, mezclando cosas"
	kept = _validate_relics(["una charla que tubimos distendida", "una charla que tuvimos distendida"], raw)
	assert kept == ["una charla que tubimos distendida"]  # typo preserved, corrected paraphrase rejected


def test_relics_caps_and_dedupe():
	raw = "alfa beta gamma " * 30
	kept = _validate_relics(["alfa beta", "alfa beta", "beta gamma", "gamma alfa"], raw)
	assert kept == ["alfa beta", "beta gamma"]  # dedupe + cap at 2


def test_fallback_includes_v3_fields(monkeypatch):
	from red_pill.core import providers

	monkeypatch.setattr(
		providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: (_ for _ in ()).throw(RuntimeError("down")))
	)
	result = distill_engram(LONG_RAW)
	assert result["_is_fallback"] is True
	assert result["texture"] == "" and result["relics"] == [] and result["lang"] == ""


def test_taxonomy_matches_prompt():
	assert "neutral" in VALID_EMOTIONS and len(VALID_EMOTIONS) == 11
