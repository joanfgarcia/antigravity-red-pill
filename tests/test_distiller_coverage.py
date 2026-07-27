"""Coverage boost for red_pill.metabolism.distiller — pure functions and branches."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from red_pill.metabolism.distiller import (
	EMOTION_SYNONYMS,
	VALID_EMOTIONS,
	build_emotional_vector,
	derive_hub_affect,
	load_distiller_config,
	load_prompt_text,
	merge_relics,
	_validate_relics,
)


class TestValidateRelics:
	def test_empty_list(self):
		assert _validate_relics([], "some content") == []

	def test_non_list_input(self):
		assert _validate_relics("not a list", "content") == []

	def test_non_string_elements(self):
		assert _validate_relics([123, None, True], "content") == []

	def test_not_substring_dropped(self):
		assert _validate_relics(["this is not in source"], "completely different") == []

	def test_substring_kept(self):
		raw = "hablamos de arquitectura de software"
		assert _validate_relics(["hablamos de arquitectura"], raw) == ["hablamos de arquitectura"]

	def test_max_len_respected(self):
		raw = "a " * 300
		long_relic = "a " * 101  # 202 chars > 200 max
		assert _validate_relics([long_relic.strip()], raw) == []

	def test_max_relics_cap(self):
		raw = "alfa beta gamma delta epsilon"
		relics = ["alfa", "beta", "gamma", "delta", "epsilon"]
		result = _validate_relics(relics, raw, max_relics=2)
		assert len(result) == 2

	def test_dedupe(self):
		raw = "alfa beta gamma"
		relics = ["alfa beta", "alfa beta", "beta gamma"]
		result = _validate_relics(relics, raw)
		assert result == ["alfa beta", "beta gamma"]

	def test_strips_quotes(self):
		raw = "una charla interesante"
		relics = ['"una charla interesante"']
		result = _validate_relics(relics, raw)
		assert result == ["una charla interesante"]

	def test_whitespace_normalized(self):
		raw = "  multiple   spaces   here  "
		relics = ["multiple spaces here"]
		result = _validate_relics(relics, raw)
		assert result == ["multiple spaces here"]


class TestDeriveHubAffect:
	def test_empty_chunks(self):
		assert derive_hub_affect([]) == ("neutral", 0.5)

	def test_single_chunk(self):
		chunks = [{"emotion": "joy", "intensity": 0.8}]
		assert derive_hub_affect(chunks) == ("joy", 0.8)

	def test_multiple_same_emotion(self):
		chunks = [
			{"emotion": "joy", "intensity": 0.5},
			{"emotion": "joy", "intensity": 0.7},
			{"emotion": "sadness", "intensity": 0.3},
		]
		dominant, max_int = derive_hub_affect(chunks)
		assert dominant == "joy"
		assert max_int == 0.7

	def test_weighted_dominant(self):
		chunks = [
			{"emotion": "fear", "intensity": 0.9},
			{"emotion": "fear", "intensity": 0.8},
			{"emotion": "joy", "intensity": 0.6},
		]
		dominant, max_int = derive_hub_affect(chunks)
		assert dominant == "fear"
		assert max_int == 0.9

	def test_missing_emotion_defaults_neutral(self):
		chunks = [{"intensity": 0.5}]
		dominant, _ = derive_hub_affect(chunks)
		assert dominant == "neutral"

	def test_missing_intensity_defaults_05(self):
		chunks = [{"emotion": "anger"}]
		_, max_int = derive_hub_affect(chunks)
		assert max_int == 0.5


class TestMergeRelics:
	def test_empty_chunks(self):
		assert merge_relics([]) == []

	def test_no_relics_in_chunks(self):
		chunks = [{"summary": "x"}, {"summary": "y"}]
		assert merge_relics(chunks) == []

	def test_merges_and_dedupes(self):
		chunks = [
			{"relics": ["quote a", "quote b"]},
			{"relics": ["quote b", "quote c"]},
		]
		assert merge_relics(chunks) == ["quote a", "quote b", "quote c"]

	def test_cap_respected(self):
		chunks = [{"relics": [f"relic-{i}" for i in range(10)]}]
		assert len(merge_relics(chunks, cap=3)) == 3

	def test_max_len_filter(self):
		chunks = [{"relics": ["x" * 300]}]
		assert merge_relics(chunks) == []

	def test_non_string_relics_skipped(self):
		chunks = [{"relics": [123, None, "valid quote"]}]
		assert merge_relics(chunks) == ["valid quote"]

	def test_empty_relics_list_in_chunk(self):
		chunks = [{"relics": []}, {"relics": None}]
		assert merge_relics(chunks) == []


class TestBuildEmotionalVector:
	def test_basic(self):
		affects = [{"child_id": "a", "emotion": "joy", "intensity": 0.8, "category": "social"}]
		result = build_emotional_vector(affects)
		assert result == {"fragments": affects}

	def test_empty(self):
		assert build_emotional_vector([]) == {"fragments": []}


class TestLoadDistillerConfig:
	def test_returns_default_when_missing(self, tmp_path):
		result = load_distiller_config(str(tmp_path / "nonexistent.yaml"))
		assert result is not None

	def test_loads_valid_yaml(self, tmp_path):
		config_file = tmp_path / "test_config.yaml"
		config_file.write_text("distill_engram:\n  temperature: 0.5\n", encoding="utf-8")
		result = load_distiller_config(str(config_file))
		assert result is not None

	def test_invalid_yaml_returns_default(self, tmp_path):
		config_file = tmp_path / "bad.yaml"
		config_file.write_text("{{invalid yaml", encoding="utf-8")
		result = load_distiller_config(str(config_file))
		assert result is not None


class TestLoadPromptText:
	def test_override_text_returned_directly(self):
		assert load_prompt_text("any.txt", override_text="custom prompt") == "custom prompt"

	def test_fallback_when_no_file(self, tmp_path):
		result = load_prompt_text("nonexistent.txt", fallback_prompt="fallback", override_text=None)
		assert result == "fallback"

	def test_reads_existing_file(self, tmp_path):
		prompt_file = tmp_path / "test_prompt.txt"
		prompt_file.write_text("  prompt content  ", encoding="utf-8")
		with patch("red_pill.metabolism.distiller.PROMPTS_DIR", str(tmp_path)):
			result = load_prompt_text("test_prompt.txt")
		assert result == "prompt content"

	def test_empty_file_returns_fallback(self, tmp_path):
		prompt_file = tmp_path / "empty.txt"
		prompt_file.write_text("", encoding="utf-8")
		with patch("red_pill.metabolism.distiller.PROMPTS_DIR", str(tmp_path)):
			result = load_prompt_text("empty.txt", fallback_prompt="fb")
		assert result == "fb"


class TestEmotionSynonyms:
	def test_synonyms_map_to_valid(self):
		for synonym, target in EMOTION_SYNONYMS.items():
			assert target in VALID_EMOTIONS, f"Synonym '{synonym}' maps to invalid '{target}'"

	def test_all_valid_emotions_present(self):
		expected = {"joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"}
		assert VALID_EMOTIONS == expected
