"""
TST-F01: ACE-CAL Mode Switching — PIONEER, ACADEMIC, CUSTOM
=============================================================
Verifies that the _build_affect_map() factory correctly selects and populates
the affect map from each of the three supported calibration models, and that
CUSTOM overrides are applied cleanly on top of the selected base.

All tests monkey-patch cfg.AFFECT_MODEL / cfg.AFFECT_CUSTOM_OVERRIDES and
call the private builder function directly to avoid module-level caching.
No network, no Qdrant, no mocks required.
"""

import json

import pytest

import red_pill.config as cfg
from red_pill.utils.affect import _ACADEMIC_MODEL, _PIONEER_MODEL, _build_affect_map

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build(model: str, overrides: str = "{}"):
	"""Build an affect map with given model and custom overrides."""
	original_model = cfg.AFFECT_MODEL
	original_overrides = cfg.AFFECT_CUSTOM_OVERRIDES
	try:
		cfg.AFFECT_MODEL = model
		cfg.AFFECT_CUSTOM_OVERRIDES = overrides
		return _build_affect_map()
	finally:
		cfg.AFFECT_MODEL = original_model
		cfg.AFFECT_CUSTOM_OVERRIDES = original_overrides


# ─────────────────────────────────────────────────────────────────────────────
# PIONEER mode
# ─────────────────────────────────────────────────────────────────────────────


class TestPioneerMode:
	def test_pioneer_selects_pioneer_base(self):
		"""PIONEER model produces the same values as _PIONEER_MODEL."""
		amap = _build("PIONEER")
		for emotion, (v, a) in _PIONEER_MODEL.items():
			assert emotion in amap, f"Missing emotion: {emotion}"
			assert amap[emotion] == pytest.approx((v, a), abs=1e-6), f"Mismatch for {emotion}"

	def test_pioneer_all_emotions_present(self):
		"""All 17 base emotions are present in PIONEER map."""
		amap = _build("PIONEER")
		assert len(amap) >= 17

	def test_pioneer_neutral_origin(self):
		"""PIONEER neutral is at (0.0, 0.0)."""
		amap = _build("PIONEER")
		assert amap["neutral"] == pytest.approx((0.0, 0.0), abs=1e-9)

	def test_pioneer_joy_positive_valence(self):
		"""PIONEER joy has positive valence > 0."""
		amap = _build("PIONEER")
		v, _ = amap["joy"]
		assert v > 0

	def test_pioneer_fear_high_arousal(self):
		"""PIONEER fear has high arousal (> 0.8)."""
		amap = _build("PIONEER")
		_, a = amap["fear"]
		assert a >= 0.8

	def test_pioneer_ennui_low_arousal(self):
		"""PIONEER ennui has low arousal (< 0.3) — fades fast."""
		amap = _build("PIONEER")
		_, a = amap["ennui"]
		assert a < 0.3


# ─────────────────────────────────────────────────────────────────────────────
# ACADEMIC mode
# ─────────────────────────────────────────────────────────────────────────────


class TestAcademicMode:
	def test_academic_selects_academic_base(self):
		"""ACADEMIC model produces the same values as _ACADEMIC_MODEL."""
		amap = _build("ACADEMIC")
		for emotion, (v, a) in _ACADEMIC_MODEL.items():
			assert emotion in amap, f"Missing emotion: {emotion}"
			assert amap[emotion] == pytest.approx((v, a), abs=1e-6), f"Mismatch for {emotion}"

	def test_academic_differs_from_pioneer(self):
		"""ACADEMIC and PIONEER models are NOT identical."""
		pioneer = _build("PIONEER")
		academic = _build("ACADEMIC")
		# At least one emotion should differ (by design)
		diffs = {e for e in pioneer if e in academic and pioneer[e] != academic[e]}
		assert len(diffs) > 0, "ACADEMIC and PIONEER models are identical — expected differences"

	def test_academic_neutral_low_arousal(self):
		"""ACADEMIC neutral has non-zero arousal (resting state) per Warriner."""
		amap = _build("ACADEMIC")
		_, a = amap["neutral"]
		assert a == pytest.approx(0.25, abs=0.01)

	def test_academic_sadness_less_extreme_than_pioneer(self):
		"""
		ACADEMIC sadness valence is less extreme than PIONEER.
		Warriner (2013) normalised values are more conservative.
		"""
		pioneer_v, _ = _build("PIONEER")["sadness"]
		academic_v, _ = _build("ACADEMIC")["sadness"]
		# Both negative; academic should be less negative (closer to 0)
		assert abs(academic_v) < abs(pioneer_v), f"Expected ACADEMIC sadness ({academic_v}) less extreme than PIONEER ({pioneer_v})"

	def test_academic_all_emotions_present(self):
		"""All 17 base emotions are present in ACADEMIC map."""
		amap = _build("ACADEMIC")
		assert len(amap) >= 17


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM overrides
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomOverrides:
	def test_custom_overrides_single_emotion_on_pioneer(self):
		"""A JSON override replaces a single emotion coordinate on PIONEER base."""
		overrides = json.dumps({"joy": [0.99, 0.01]})
		amap = _build("PIONEER", overrides)
		assert amap["joy"] == pytest.approx((0.99, 0.01), abs=1e-9)

	def test_custom_overrides_single_emotion_on_academic(self):
		"""A JSON override replaces a single emotion coordinate on ACADEMIC base."""
		overrides = json.dumps({"fear": [-1.0, 1.0]})
		amap = _build("ACADEMIC", overrides)
		assert amap["fear"] == pytest.approx((-1.0, 1.0), abs=1e-9)
		# Other emotions remain unchanged
		assert amap["joy"] == pytest.approx(_ACADEMIC_MODEL["joy"], abs=1e-6)

	def test_custom_overrides_new_emotion(self):
		"""A new emotion not in the base model can be added via CUSTOM overrides."""
		overrides = json.dumps({"awe": [0.6, 0.85]})
		amap = _build("PIONEER", overrides)
		assert "awe" in amap
		assert amap["awe"] == pytest.approx((0.6, 0.85), abs=1e-9)

	def test_custom_overrides_multiple_emotions(self):
		"""Multiple overrides can be applied in a single JSON payload."""
		overrides = json.dumps({"joy": [0.5, 0.5], "fear": [-0.5, 0.5], "neutral": [0.1, 0.1]})
		amap = _build("PIONEER", overrides)
		assert amap["joy"] == pytest.approx((0.5, 0.5), abs=1e-9)
		assert amap["fear"] == pytest.approx((-0.5, 0.5), abs=1e-9)
		assert amap["neutral"] == pytest.approx((0.1, 0.1), abs=1e-9)

	def test_invalid_json_does_not_crash(self):
		"""Malformed CUSTOM_OVERRIDES JSON is silently ignored — PIONEER base returned."""
		amap = _build("PIONEER", "{not valid json}")
		# Should fall back gracefully to PIONEER values
		assert amap["joy"] == pytest.approx(_PIONEER_MODEL["joy"], abs=1e-6)

	def test_invalid_coords_format_ignored(self):
		"""Overrides with wrong coordinate format are skipped — base value preserved."""
		overrides = json.dumps({"joy": "not_a_list"})
		amap = _build("PIONEER", overrides)
		# joy should still be the PIONEER value
		assert amap["joy"] == pytest.approx(_PIONEER_MODEL["joy"], abs=1e-6)

	def test_empty_overrides_returns_base(self):
		"""Empty overrides dict `{}` returns the base model unchanged."""
		pioneer = _build("PIONEER", "{}")
		for emotion, coords in _PIONEER_MODEL.items():
			assert pioneer[emotion] == pytest.approx(coords, abs=1e-9)

	def test_unknown_model_falls_back_to_pioneer(self):
		"""An unknown AFFECT_MODEL string triggers a warning and falls back to PIONEER."""
		amap = _build("CUSTOM_NOT_EXIST")
		# Should match PIONEER
		for emotion, coords in _PIONEER_MODEL.items():
			assert amap[emotion] == pytest.approx(coords, abs=1e-6)
