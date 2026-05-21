"""
TST-MR-001: ModelRegistry — VRAM Tier Resolution & Cache
==========================================================
Tests for `red_pill.core.model_registry`:
  - Profile loading (missing file → empty dict, valid YAML → profiles loaded)
  - get_profile / get_profile_by_capability
  - VRAM tier selection: lowest tier, middle tier, highest tier, exceeds all tiers
  - VRAM cache: same value returned within TTL, refreshed after TTL expires
  - Graceful degradation when sentinel is unavailable

All tests are hermetic: no GPU required, no filesystem side-effects.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tiered_hardware():
	"""Minimal model_profiles-style hardware_affinity with three VRAM tiers."""
	return {
		"vram_tiers": [
			{"limit_gb": 4.0, "n_gpu_layers": 10, "n_ctx": 2048},
			{"limit_gb": 8.0, "n_gpu_layers": 20, "n_ctx": 4096},
			{"limit_gb": 16.0, "n_gpu_layers": 35, "n_ctx": 8192},
		]
	}


def _make_profile(hardware: dict) -> dict:
	return {"capabilities": ["distillation"], "hardware_affinity": hardware}


def _stats_for(vram_mb: int) -> dict:
	"""Build a fake sentinel.get_stats() response for a given VRAM in MB."""
	return {"gpu": [{"memory": f"0/{vram_mb} MB", "name": "FakeGPU"}]}


# ── Tests: _get_vram_gb cache ─────────────────────────────────────────────────

class TestVramCache:
	def setup_method(self):
		"""Reset the module-level cache before every test."""
		import red_pill.core.model_registry as mr
		mr._VRAM_CACHE = None

	def test_cache_miss_calls_sentinel(self):
		"""First call must hit sentinel.get_stats()."""
		import red_pill.core.model_registry as mr

		mock_sentinel = MagicMock()
		mock_sentinel.get_stats.return_value = _stats_for(8192)

		with patch.dict("sys.modules", {"red_pill.telemetry.sentinel": mock_sentinel}):
			with patch("red_pill.telemetry.sentinel", mock_sentinel):
				result = mr._get_vram_gb()

		assert result == pytest.approx(8.0)
		mock_sentinel.get_stats.assert_called_once()

	def test_cache_hit_skips_sentinel(self):
		"""Second call within TTL must NOT call sentinel again."""
		import red_pill.core.model_registry as mr

		mock_sentinel = MagicMock()
		mock_sentinel.get_stats.return_value = _stats_for(4096)

		with patch("red_pill.telemetry.sentinel", mock_sentinel):
			mr._get_vram_gb()  # First call — populates cache
			mr._get_vram_gb()  # Second call — should hit cache

		assert mock_sentinel.get_stats.call_count == 1

	def test_cache_expired_calls_sentinel_again(self):
		"""After TTL expiry the cache must be refreshed."""
		import red_pill.core.model_registry as mr

		# Plant a stale cache entry (timestamp well in the past)
		mr._VRAM_CACHE = (time.monotonic() - 99999, 4.0)
		old_ttl = mr._VRAM_CACHE_TTL_SECONDS
		mr._VRAM_CACHE_TTL_SECONDS = 1.0  # 1 second TTL

		try:
			mock_sentinel = MagicMock()
			mock_sentinel.get_stats.return_value = _stats_for(8192)

			with patch("red_pill.telemetry.sentinel", mock_sentinel):
				result = mr._get_vram_gb()

			assert result == pytest.approx(8.0)
			mock_sentinel.get_stats.assert_called_once()
		finally:
			mr._VRAM_CACHE_TTL_SECONDS = old_ttl

	def test_sentinel_failure_returns_zero(self):
		"""If sentinel raises, _get_vram_gb must return 0.0 without crashing."""
		import red_pill.core.model_registry as mr

		mock_sentinel = MagicMock()
		mock_sentinel.get_stats.side_effect = RuntimeError("GPU not found")

		with patch("red_pill.telemetry.sentinel", mock_sentinel):
			result = mr._get_vram_gb()

		assert result == 0.0

	def test_ttl_zero_disables_cache(self):
		"""When TTL is 0, every call should hit sentinel."""
		import red_pill.core.model_registry as mr

		old_ttl = mr._VRAM_CACHE_TTL_SECONDS
		mr._VRAM_CACHE_TTL_SECONDS = 0.0

		try:
			mock_sentinel = MagicMock()
			mock_sentinel.get_stats.return_value = _stats_for(4096)

			with patch("red_pill.telemetry.sentinel", mock_sentinel):
				mr._get_vram_gb()
				mr._get_vram_gb()

			assert mock_sentinel.get_stats.call_count == 2
		finally:
			mr._VRAM_CACHE_TTL_SECONDS = old_ttl


# ── Tests: VRAM tier selection ────────────────────────────────────────────────

class TestVramTierResolution:
	def setup_method(self):
		"""Reset profiles cache and VRAM cache before every test."""
		import red_pill.core.model_registry as mr
		mr.ModelRegistry._profiles_cache = None
		mr._VRAM_CACHE = None

	def _setup_registry(self, vram_mb: int, hardware: dict):
		"""Patch ModelRegistry so it returns the given hardware config without disk I/O."""
		import red_pill.core.model_registry as mr

		profile = _make_profile(hardware)
		mr.ModelRegistry._profiles_cache = {"test_profile": profile}

		mock_sentinel = MagicMock()
		mock_sentinel.get_stats.return_value = _stats_for(vram_mb)
		return mock_sentinel

	def test_lowest_tier_selected_for_minimal_vram(self):
		"""2 GB VRAM → smallest tier (limit_gb=4.0) must be selected."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(2048, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result["n_gpu_layers"] == 10
		assert result["n_ctx"] == 2048

	def test_middle_tier_selected_for_mid_vram(self):
		"""6 GB VRAM → middle tier (limit_gb=8.0) must be selected."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(6144, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result["n_gpu_layers"] == 20
		assert result["n_ctx"] == 4096

	def test_highest_tier_selected_for_max_vram(self):
		"""12 GB VRAM → highest tier (limit_gb=16.0) must be selected."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(12288, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result["n_gpu_layers"] == 35
		assert result["n_ctx"] == 8192

	def test_exceeds_all_tiers_uses_highest(self):
		"""32 GB VRAM (exceeds all limits) → last/highest tier must be used."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(32768, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result["n_gpu_layers"] == 35

	def test_limit_gb_not_present_in_resolved(self):
		"""The internal 'limit_gb' key must be stripped from the resolved dict."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(2048, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert "limit_gb" not in result

	def test_vram_tiers_not_present_in_resolved(self):
		"""The 'vram_tiers' key must not appear in the resolved hardware affinity."""
		import red_pill.core.model_registry as mr

		sentinel = self._setup_registry(4096, _make_tiered_hardware())
		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert "vram_tiers" not in result

	def test_base_keys_preserved_in_resolved(self):
		"""Non-tier base keys (e.g. 'n_batch') must pass through unchanged."""
		import red_pill.core.model_registry as mr

		hw = _make_tiered_hardware()
		hw["n_batch"] = 512  # Extra base-level key

		mr.ModelRegistry._profiles_cache = {"test_profile": _make_profile(hw)}
		sentinel = MagicMock()
		sentinel.get_stats.return_value = _stats_for(2048)

		with patch("red_pill.telemetry.sentinel", sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result.get("n_batch") == 512

	def test_no_vram_tiers_returns_hardware_as_is(self):
		"""Without vram_tiers, hardware_affinity must be returned verbatim."""
		import red_pill.core.model_registry as mr

		hw = {"n_gpu_layers": 99, "n_ctx": 1024}
		mr.ModelRegistry._profiles_cache = {"test_profile": _make_profile(hw)}

		result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		assert result == hw

	def test_unknown_profile_returns_empty(self):
		"""Querying a non-existent profile must return an empty dict without crash."""
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {}
		result = mr.ModelRegistry.get_resolved_hardware_affinity("non_existent")

		assert result == {}

	def test_sentinel_failure_falls_back_to_lowest_tier(self):
		"""If VRAM detection fails, VRAM=0 → lowest tier must be selected."""
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {"test_profile": _make_profile(_make_tiered_hardware())}

		mock_sentinel = MagicMock()
		mock_sentinel.get_stats.side_effect = RuntimeError("Driver crash")

		with patch("red_pill.telemetry.sentinel", mock_sentinel):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")

		# VRAM=0.0 → first tier (limit_gb=4.0) is selected
		assert result["n_gpu_layers"] == 10


# ── Tests: get_profile_by_capability ─────────────────────────────────────────

class TestGetProfileByCapability:
	def setup_method(self):
		import red_pill.core.model_registry as mr
		mr.ModelRegistry._profiles_cache = None

	def test_returns_matching_profile(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {
			"alpha": {"capabilities": ["embedding"], "hardware_affinity": {}},
			"beta": {"capabilities": ["distillation", "chat"], "hardware_affinity": {}},
		}
		name, profile = mr.ModelRegistry.get_profile_by_capability("distillation")

		assert name == "beta"
		assert "distillation" in profile["capabilities"]

	def test_fallback_to_first_profile_when_no_match(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {
			"only_one": {"capabilities": ["embedding"], "hardware_affinity": {}},
		}
		name, profile = mr.ModelRegistry.get_profile_by_capability("does_not_exist")

		assert name == "only_one"

	def test_empty_cache_returns_empty(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {}
		name, profile = mr.ModelRegistry.get_profile_by_capability("anything")

		assert name == ""
		assert profile == {}
