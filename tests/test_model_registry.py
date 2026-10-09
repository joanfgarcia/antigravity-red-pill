"""
TST-MR-002: ModelRegistry — VRAM Tier Resolution via VramProbe
==============================================================
Tests for `red_pill.core.model_registry` after the VramProbe refactor:
  - Profile loading (missing file → empty dict, valid YAML → profiles loaded)
  - get_profile / get_profile_by_capability
  - VRAM tier selection via free VRAM: lowest, middle, highest, exceeds all
  - min_free_gb key naming (renamed from limit_gb)
  - Graceful degradation when VramProbe returns 0 (sentinel failure or CPU)

All tests are hermetic: no GPU required, no filesystem side-effects.
"""

from unittest.mock import patch

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tiered_hardware():
	"""Minimal hardware_affinity with three VRAM tiers using min_free_gb."""
	return {
		"vram_tiers": [
			{"min_free_gb": 2.0, "n_gpu_layers": 10, "n_ctx": 2048},
			{"min_free_gb": 4.0, "n_gpu_layers": 20, "n_ctx": 4096},
			{"min_free_gb": 7.0, "n_gpu_layers": 35, "n_ctx": 8192},
		]
	}


def _make_profile(hardware: dict) -> dict:
	return {"capabilities": ["distillation"], "hardware_affinity": hardware}


def _patch_free_mb(free_mb: int):
	"""Patch VramProbe.get_free_mb() to return a fixed value."""
	return patch("red_pill.core.model_registry.VramProbe.get_free_mb", return_value=free_mb)


# ── Tests: VRAM tier selection ────────────────────────────────────────────────


class TestVramTierResolution:
	def setup_method(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = None

	def _setup_profile(self, hardware: dict):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {"test_profile": _make_profile(hardware)}

	def test_lowest_tier_selected_for_minimal_free_vram(self):
		"""1.5 GB free → lowest tier (min_free_gb=2.0) must be selected."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(1536):  # 1.5 GB
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result["n_gpu_layers"] == 10
		assert result["n_ctx"] == 2048

	def test_middle_tier_selected_for_mid_free_vram(self):
		"""5 GB free → middle tier (min_free_gb=4.0) must be selected.

		Fixed via the 2026-08-13 patch: tier selection now uses `free >= min`
		(highest fitting tier). Previously used `free <= min` which forced the
		wrong tier when free VRAM exceeded all demoted thresholds.
		"""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(5120):  # 5 GB
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result["n_gpu_layers"] == 20
		assert result["n_ctx"] == 4096

	def test_highest_tier_selected_for_high_free_vram(self):
		"""8 GB free → highest tier (min_free_gb=7.0) must be selected."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(8192):  # 8 GB
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result["n_gpu_layers"] == 35
		assert result["n_ctx"] == 8192

	def test_exceeds_all_tiers_uses_highest(self):
		"""16 GB free (exceeds all tiers) → last/highest tier must be used."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(16384):  # 16 GB
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result["n_gpu_layers"] == 35

	def test_min_free_gb_not_present_in_resolved(self):
		"""The internal 'min_free_gb' key must be stripped from the resolved dict."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(1024):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert "min_free_gb" not in result

	def test_vram_tiers_not_present_in_resolved(self):
		"""The 'vram_tiers' key must not appear in the resolved hardware affinity."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(2048):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert "vram_tiers" not in result

	def test_base_keys_preserved_in_resolved(self):
		"""Non-tier base keys (e.g. 'n_batch') must pass through unchanged."""
		hw = _make_tiered_hardware()
		hw["n_batch"] = 512
		self._setup_profile(hw)
		import red_pill.core.model_registry as mr

		with _patch_free_mb(1024):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result.get("n_batch") == 512

	def test_no_vram_tiers_returns_hardware_as_is(self):
		"""Without vram_tiers, hardware_affinity must be returned verbatim."""
		hw = {"n_gpu_layers": 99, "n_ctx": 1024}
		self._setup_profile(hw)
		import red_pill.core.model_registry as mr

		result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
		assert result == hw

	def test_unknown_profile_returns_empty(self):
		"""Querying a non-existent profile must return an empty dict without crash."""
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {}
		result = mr.ModelRegistry.get_resolved_hardware_affinity("non_existent")
		assert result == {}

	def test_zero_free_vram_falls_back_to_lowest_tier(self):
		"""0 MB free (CPU or probe failure) → lowest tier must be selected."""
		self._setup_profile(_make_tiered_hardware())
		import red_pill.core.model_registry as mr

		with _patch_free_mb(0):
			result = mr.ModelRegistry.get_resolved_hardware_affinity("test_profile")
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


# ── Tests: plan de KV por calidad (RFC-HARNESS-003 §2.7) ─────────────────────


class TestKvPlan:
	def setup_method(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = None

	def _setup(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {
			"bonsai": {
				"kv_cache": {
					"preferred": "f16",
					"fallbacks": ["q8_0", "q4_0"],
					"bytes_per_token_kib": {"f16": 64, "q8_0": 34, "q4_0": 18},
				},
				"vram_footprint": {"weights_mb": 5536, "overhead_mb": 330},
				"hardware_affinity": {"n_ctx": 24576},
			}
		}

	def test_f16_kept_when_it_fits(self):
		self._setup()
		import red_pill.core.model_registry as mr

		plan = mr.ModelRegistry.plan_kv_cache("bonsai", ctx=24576, free_mb=8000)
		assert plan["kv_type"] == "f16"
		assert plan["fits"] and not plan["degraded"]
		assert plan["required_mb"] == 5536 + 330 + 1536

	def test_degrades_to_q8_conserving_ctx(self):
		self._setup()
		import red_pill.core.model_registry as mr

		plan = mr.ModelRegistry.plan_kv_cache("bonsai", ctx=24576, free_mb=7000)
		assert plan["kv_type"] == "q8_0"
		assert plan["fits"] and plan["degraded"]
		assert plan["ctx"] == 24576  # el contexto se conserva; cede la KV

	def test_degrades_to_q4_for_64k_ctx(self):
		self._setup()
		import red_pill.core.model_registry as mr

		plan = mr.ModelRegistry.plan_kv_cache("bonsai", ctx=65536, free_mb=7200)
		assert plan["kv_type"] == "q4_0"
		assert plan["fits"]

	def test_none_fits_reports_clean(self):
		self._setup()
		import red_pill.core.model_registry as mr

		plan = mr.ModelRegistry.plan_kv_cache("bonsai", ctx=65536, free_mb=5000)
		assert plan["fits"] is False
		assert plan["kv_type"] is None

	def test_no_kv_data_returns_empty(self):
		import red_pill.core.model_registry as mr

		mr.ModelRegistry._profiles_cache = {"x": {"hardware_affinity": {}}}
		assert mr.ModelRegistry.plan_kv_cache("x", ctx=8192, free_mb=8000) == {}

	def test_default_ctx_is_the_desired_profile_context(self):
		self._setup()
		import red_pill.core.model_registry as mr

		plan = mr.ModelRegistry.plan_kv_cache("bonsai", free_mb=8000)
		assert plan["ctx"] == 24576  # el contexto deseado manda; la KV cede
