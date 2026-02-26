"""
TST-001: ACE Engine — Affect & Stability Multiplier Unit Tests
=================================================================
Dedicated parametrized tests for `red_pill.utils.affect`:
  - get_affect_coordinates()
  - get_emotional_stability_multiplier()

All tests operate on pure math — no Qdrant, no network, no mocks required.
The functions are stateless and deterministic.

Boundary cases (as requested by the independent audit, Confidence ←→ 91/100):
  1. Empty emotion list
  2. All-neutral emotions
  3. Single high-arousal emotion (flashbulb memory)
  4. Single negative-valence emotion (survival persistence)
  5. Mixed positive/negative valence (averaging)
  6. Maximum intensity (10.0)
  7. Minimum intensity (0.0 / 1.0 boundary)
  8. Unknown / unrecognised emotion labels
  9. Output always clamped to [0.1, 1.0]
 10. High-arousal + high-intensity → low multiplier (slower decay)
 11. Low-arousal + neutral valence → multiplier close to 1.0 (fast decay)
"""

import pytest

from red_pill.utils.affect import (
    AFFECT_MAP,
    get_affect_coordinates,
    get_emotional_stability_multiplier,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _within(value: float, lo: float, hi: float) -> bool:
	"""Returns True if lo <= value <= hi."""
	return lo <= value <= hi


# ─────────────────────────────────────────────────────────────────────────────
# get_affect_coordinates — parametrized
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAffectCoordinates:
	"""Tests for the Russell Circumplex coordinate mapper."""

	def test_empty_list_returns_origin(self):
		"""No emotions → (0.0, 0.0) — neutral origin of the Circumplex."""
		v, a = get_affect_coordinates([])
		assert v == 0.0
		assert a == 0.0

	def test_single_neutral_returns_origin(self):
		v, a = get_affect_coordinates(["neutral"])
		assert v == 0.0
		assert a == 0.0

	def test_single_joy(self):
		v, a = get_affect_coordinates(["joy"])
		exp_v, exp_a = AFFECT_MAP["joy"]
		assert v == pytest.approx(exp_v)
		assert a == pytest.approx(exp_a)

	def test_single_fear(self):
		"""Fear: negative valence, high arousal (survival-critical)."""
		v, a = get_affect_coordinates(["fear"])
		exp_v, exp_a = AFFECT_MAP["fear"]
		assert v == pytest.approx(exp_v)
		assert a == pytest.approx(exp_a)
		assert v < 0   # negative valence
		assert a > 0.5  # high arousal

	def test_average_of_two_known_emotions(self):
		"""Averaging across joy and sadness should yield intermediate coordinates."""
		v, a = get_affect_coordinates(["joy", "sadness"])
		exp_v = (AFFECT_MAP["joy"][0] + AFFECT_MAP["sadness"][0]) / 2
		exp_a = (AFFECT_MAP["joy"][1] + AFFECT_MAP["sadness"][1]) / 2
		assert v == pytest.approx(exp_v, abs=1e-9)
		assert a == pytest.approx(exp_a, abs=1e-9)

	def test_unknown_emotion_ignored(self):
		"""Unrecognised labels are silently skipped; only known ones contribute."""
		v_known, a_known = get_affect_coordinates(["joy"])
		v_mixed, a_mixed = get_affect_coordinates(["joy", "completely_unknown_emotion"])
		assert v_mixed == pytest.approx(v_known)
		assert a_mixed == pytest.approx(a_known)

	def test_all_unknown_returns_origin(self):
		"""If all labels are unknown, default to (0.0, 0.0)."""
		v, a = get_affect_coordinates(["foo", "bar", "baz"])
		assert v == 0.0
		assert a == 0.0

	def test_case_insensitive(self):
		"""Emotion labels should be matched case-insensitively."""
		v_lower, a_lower = get_affect_coordinates(["joy"])
		v_upper, a_upper = get_affect_coordinates(["JOY"])
		assert v_lower == pytest.approx(v_upper)
		assert a_lower == pytest.approx(a_upper)

	@pytest.mark.parametrize("emotion", list(AFFECT_MAP.keys()))
	def test_all_known_emotions_return_valid_coordinates(self, emotion):
		"""Every emotion in the AFFECT_MAP must return valid Circumplex coords."""
		v, a = get_affect_coordinates([emotion])
		assert -1.0 <= v <= 1.0, f"{emotion}: valence out of range"
		assert  0.0 <= a <= 1.0, f"{emotion}: arousal out of range"


# ─────────────────────────────────────────────────────────────────────────────
# get_emotional_stability_multiplier — parametrized boundary cases
# ─────────────────────────────────────────────────────────────────────────────

class TestGetEmotionalStabilityMultiplier:
	"""
	Tests for the ACE stability multiplier.

	Contract:
	  - Output ∈ [0.1, 1.0]  (hard clamp, always)
	  - 0.1 = 10x slower decay (maximum stability)
	  - 1.0 = normal decay (minimum stability)
	  - High arousal + high intensity → lower multiplier (more stable)
	  - Neutral / low-arousal → multiplier approaches 1.0 (faster decay)
	  - Negative valence increases stability (survival mechanism)
	"""

	# ── Contract: output always in [0.1, 1.0] ──────────────────────────────

	@pytest.mark.parametrize("emotions,intensity", [
		([], 1.0),
		(["neutral"], 1.0),
		(["joy"], 10.0),
		(["fear"], 10.0),
		(["anger"], 10.0),
		(["ennui"], 1.0),
		(["fear", "anger"], 10.0),
		(["joy", "sadness", "neutral"], 5.0),
		(["completely_unknown"], 10.0),
		([], 10.0),
		(["joy"], 0.0),
	])
	def test_output_always_in_valid_range(self, emotions, intensity):
		"""Clamp contract: result must always be in [0.1, 1.0]."""
		result = get_emotional_stability_multiplier(emotions, intensity)
		assert _within(result, 0.1, 1.0), (
			f"Out of range for emotions={emotions}, intensity={intensity}: got {result}"
		)

	# ── Boundary: empty / neutral ───────────────────────────────────────────

	def test_empty_emotions_default_intensity_returns_near_one(self):
		"""No emotional signal → maximum decay (multiplier ≈ 1.0)."""
		result = get_emotional_stability_multiplier([], intensity=1.0)
		assert result == pytest.approx(1.0), (
			f"Expected ~1.0 for empty emotions, got {result}"
		)

	def test_all_neutral_emotions_returns_one(self):
		"""Pure neutral affects → no stability boost, multiplier = 1.0."""
		result = get_emotional_stability_multiplier(["neutral"], intensity=1.0)
		assert result == pytest.approx(1.0)

	def test_multiple_neutral_returns_one(self):
		result = get_emotional_stability_multiplier(["neutral", "neutral"], intensity=1.0)
		assert result == pytest.approx(1.0)

	# ── Boundary: single high-arousal emotion ──────────────────────────────

	def test_single_high_arousal_fear_at_max_intensity_is_stable(self):
		"""
		fear: arousal=0.9 (highest), intensity=10 → effective_arousal=min(0.9*2, 1.0)=1.0
		valence_stability = abs(-0.6) = 0.6
		stability = 0.7*1.0 + 0.3*0.6 = 0.88
		multiplier = max(0.1, 1.0 - 0.88*0.9) = max(0.1, 0.208) = 0.208
		→ Should be well below 0.5 (high stability = slow decay)
		"""
		result = get_emotional_stability_multiplier(["fear"], intensity=10.0)
		assert result < 0.5, f"High-arousal fear at max intensity should be very stable, got {result}"
		assert _within(result, 0.1, 1.0)

	def test_single_high_arousal_anger_at_max_intensity(self):
		"""anger: arousal=0.9, valence=-0.7 → should produce low multiplier."""
		result = get_emotional_stability_multiplier(["anger"], intensity=10.0)
		assert result < 0.5
		assert _within(result, 0.1, 1.0)

	def test_high_arousal_surprise_at_max_intensity(self):
		"""surprise: highest arousal=0.9 but weak positive valence=0.3."""
		result = get_emotional_stability_multiplier(["surprise"], intensity=10.0)
		assert result < 0.5
		assert _within(result, 0.1, 1.0)

	# ── Boundary: intensity scaling ─────────────────────────────────────────

	def test_zero_intensity_produces_near_one_multiplier(self):
		"""
		intensity=0 → effective_arousal = min(arousal * 0, 1) = 0.0
		Only valence_stability contributes, but weakly.
		For positive valence (joy): multiplier should be close to 1.0.
		"""
		result = get_emotional_stability_multiplier(["joy"], intensity=0.0)
		# joy valence=0.8 → valence_stability = 0.5*0.8 = 0.4
		# stability = 0.7*0 + 0.3*0.4 = 0.12  → multiplier = 1.0 - 0.12*0.9 = 0.892
		assert result > 0.8, f"Zero intensity joy should be weakly stable, got {result}"
		assert _within(result, 0.1, 1.0)

	@pytest.mark.parametrize("intensity_low,intensity_high,emotion", [
		(1.0, 5.0, "fear"),
		(1.0, 10.0, "anger"),
		(1.0, 8.0, "joy"),
	])
	def test_higher_intensity_yields_lower_or_equal_multiplier(self, intensity_low, intensity_high, emotion):
		"""Monotonicity: more intense memories should be at least as stable (lower multiplier)."""
		result_low = get_emotional_stability_multiplier([emotion], intensity=intensity_low)
		result_high = get_emotional_stability_multiplier([emotion], intensity=intensity_high)
		assert result_high <= result_low + 1e-9, (
			f"{emotion}: higher intensity should be more stable. "
			f"low={result_low:.4f}, high={result_high:.4f}"
		)

	# ── Boundary: valence direction ─────────────────────────────────────────

	def test_negative_valence_more_stable_than_positive_at_same_arousal(self):
		"""
		The 'survival mechanism': negative valence confers more stability
		than equivalent positive valence (abs(v) vs 0.5*v).
		Compare emotions with similar arousal but opposite valence.
		"""
		# fear: valence=-0.6, arousal=0.9
		# joy: valence=0.8, arousal=0.7 (close arousal, positive valence)
		# At equal intensity, negative-valence emotion should be more stable.
		result_neg = get_emotional_stability_multiplier(["fear"], intensity=5.0)
		result_pos = get_emotional_stability_multiplier(["joy"], intensity=5.0)
		# fear has negative valence → valence_stability = 0.6; joy → 0.4
		# fear should be ≤ joy multiplier (same or more stable)
		assert result_neg <= result_pos + 1e-9, (
			f"Negative valence (fear={result_neg:.4f}) should be at least as stable "
			f"as positive (joy={result_pos:.4f})"
		)

	def test_ennui_decays_fast(self):
		"""
		ennui: valence=-0.5, arousal=0.1 (very low arousal).
		Low arousal → low stability → multiplier close to 1.0 (fast decay).
		"""
		result = get_emotional_stability_multiplier(["ennui"], intensity=1.0)
		assert result > 0.7, f"Ennui (low arousal) should decay fast, got {result}"

	# ── Boundary: mixed valence ─────────────────────────────────────────────

	def test_mixed_positive_negative_valence_averages(self):
		"""
		joy+sadness averages to near-neutral valence but keeps moderate arousal.
		Result should be in a middle range.
		"""
		result = get_emotional_stability_multiplier(["joy", "sadness"], intensity=5.0)
		assert _within(result, 0.1, 1.0)
		# Neither very stable nor very unstable
		assert 0.2 < result < 0.9, f"Mixed valence should be moderate, got {result}"

	# ── Boundary: unknown emotions ──────────────────────────────────────────

	def test_all_unknown_emotions_returns_one(self):
		"""Unknown emotions → (0,0) coordinates → stability=0 → multiplier=1.0."""
		result = get_emotional_stability_multiplier(["foo", "bar"], intensity=10.0)
		assert result == pytest.approx(1.0)

	def test_partial_unknown_ignored_gracefully(self):
		"""Known emotions still contribute even if list contains unknowns."""
		result_known = get_emotional_stability_multiplier(["fear"], intensity=5.0)
		result_mixed = get_emotional_stability_multiplier(["fear", "unknown_xyz"], intensity=5.0)
		assert result_known == pytest.approx(result_mixed, abs=1e-9)

	# ── Explicit formula verification ──────────────────────────────────────

	def test_explicit_calculation_anxiety_intensity_5(self):
		"""
		Explicit formula check for anxiety at intensity=5 (mid-range):
		  anxiety: valence=-0.5, arousal=0.8
		  effective_arousal = min(0.8 * (5/5), 1.0) = 0.8
		  valence_stability = abs(-0.5) = 0.5   (negative valence path)
		  stability = 0.7*0.8 + 0.3*0.5 = 0.56 + 0.15 = 0.71
		  multiplier = max(0.1, 1.0 - 0.71*0.9) = max(0.1, 0.361) = 0.361
		"""
		result = get_emotional_stability_multiplier(["anxiety"], intensity=5.0)
		assert result == pytest.approx(0.361, abs=0.001)

	def test_explicit_calculation_joy_intensity_5(self):
		"""
		joy: valence=0.8, arousal=0.7
		  effective_arousal = min(0.7 * 1.0, 1.0) = 0.7
		  valence_stability = 0.5 * 0.8 = 0.4  (positive valence path)
		  stability = 0.7*0.7 + 0.3*0.4 = 0.49 + 0.12 = 0.61
		  multiplier = max(0.1, 1.0 - 0.61*0.9) = max(0.1, 0.451) = 0.451
		"""
		result = get_emotional_stability_multiplier(["joy"], intensity=5.0)
		assert result == pytest.approx(0.451, abs=0.001)

	def test_explicit_calculation_neutral_any_intensity(self):
		"""
		neutral: valence=0.0, arousal=0.0
		  effective_arousal = 0.0
		  valence_stability = 0.0
		  stability = 0.0
		  multiplier = max(0.1, 1.0 - 0.0) = 1.0
		"""
		for intensity in [0.0, 1.0, 5.0, 10.0]:
			result = get_emotional_stability_multiplier(["neutral"], intensity=intensity)
			assert result == pytest.approx(1.0), f"intensity={intensity}"
