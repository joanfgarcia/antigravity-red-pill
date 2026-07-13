"""
Unit tests for scripts/distiller_bakeoff.py scoring heuristics (no model needed).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from distiller_bakeoff import detect_language, extract_json, score_output  # noqa: E402


def test_detect_language():
	assert detect_language("Arreglado el leaf_index según la RFC") == "es"
	assert detect_language("Fixed the leaf index per the spec document here") == "en"
	assert detect_language("") == "empty"
	assert detect_language("el gato duerme en la casa") == "es"  # stopwords, no accents


def test_extract_json():
	assert extract_json('prefix {"a": 1} suffix') == {"a": 1}
	assert extract_json("no json here") is None
	assert extract_json('{"broken": ') is None


def test_score_good_spanish_output():
	raw = '{"summary": "Arreglado el bug de tree_hash en pure-mls incluyendo el leaf_index.", "emotion": "joy", "intensity": 0.6, "category": "work"}'
	s = score_output(raw)
	assert s["json_ok"] and s["has_keys"]
	assert s["summary_lang"] == "es"
	assert not s["has_think_tags"]
	assert not s["echoes_prompt"]
	assert s["emotion_valid"] and s["intensity_valid"]


def test_score_flags_think_tags_and_bad_fields():
	raw = '<think>let me reason</think>\n{"summary": "x", "emotion": "excited", "intensity": 5, "category": "work"}'
	s = score_output(raw)
	assert s["has_think_tags"]
	assert not s["emotion_valid"]  # 'excited' not in the allowed set
	assert not s["intensity_valid"]  # 5 out of [0,1]


def test_score_flags_template_echo():
	raw = '{"summary": "Synthesize these memory chunks into a cohesive master summary.", "emotion": "neutral", "intensity": 0.1, "category": "work"}'
	s = score_output(raw)
	assert s["echoes_prompt"]


def test_score_non_json_output():
	s = score_output("I cannot help with that.")
	assert not s["json_ok"]
	assert not s["has_keys"]
	assert s["echoes_prompt"]  # empty summary counts as echo/garbage
