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


def test_voice_prompt_renders_without_keyerror():
	# distiller_v3_voice.txt carries literal JSON braces; str.format would raise
	# KeyError — the renderer must use .replace (bake-off 2026-08-13 regression).
	from red_pill.metabolism.distiller import load_prompt_text

	text = load_prompt_text("distiller_v3_voice.txt")
	assert text, "distiller_v3_voice.txt missing or empty"
	rendered = text.replace("{agent_name}", "Aleth").replace("{operator_name}", "Joan")
	assert "{agent_name}" not in rendered and "{operator_name}" not in rendered


def test_voice_prompt_flows_through_distill_engram(monkeypatch):
	# End-to-end: force the voice prompt via override_params and confirm the
	# provider receives a rendered system prompt (no crash, no raw placeholders).
	provider = _mock_provider(monkeypatch, {"summary": "s", "emotion": "joy", "intensity": 0.5, "category": "social", "lang": "es"})
	result = distill_engram(LONG_RAW, override_params={"prompt_file": "distiller_v3_voice.txt"})
	assert not result.get("_is_fallback")
	system_msg = provider.generate.call_args.kwargs["messages"][0]["content"]
	assert "{agent_name}" not in system_msg and "Aleth" in system_msg


def test_profile_prompt_routing_beats_params_default(monkeypatch):
	# params yaml always ships a prompt_file default; the per-model routing from
	# the active profile must still win (otherwise the routing is dead code).
	import red_pill.metabolism.distiller as dist

	monkeypatch.setattr(dist, "_resolve_prompt_for_profile", lambda profile_name=None: "distiller_v3_voice.txt")
	seen = {}
	real_load = dist.load_prompt_text

	def spy(filename, fallback_prompt="", override_text=None):
		seen["prompt_file"] = filename
		return real_load(filename, fallback_prompt, override_text)

	monkeypatch.setattr(dist, "load_prompt_text", spy)
	_mock_provider(monkeypatch, {"summary": "s", "emotion": "joy", "intensity": 0.5, "category": "social", "lang": "es"})
	distill_engram(LONG_RAW)
	assert seen["prompt_file"] == "distiller_v3_voice.txt"


def test_correct_lang_label_respects_non_es_en_labels():
	from red_pill.metabolism.distiller import _correct_lang_label

	catalan = "M'agrada la memòria històrica i la conversa d'ahir sobre allò que vàrem fer"
	assert _correct_lang_label("ca", catalan) == "ca"  # accents must not force 'es'
	assert _correct_lang_label("en", "hola qué tal, ¿vienes mañana a la reunión?") == "es"
