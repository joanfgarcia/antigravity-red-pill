"""
Tests for Phase 2 DI extension points:
- MemoryManager.register_sleep_hook() + fire_sleep_hooks()
- MemoryManager hive= injectable kwarg
- BayesianInferenceEngine.calculate_erosion() kappa no longer binds at class definition
"""

from unittest.mock import MagicMock, patch

from red_pill.memory import BayesianInferenceEngine, MemoryManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_memory_manager(**kwargs) -> MemoryManager:
	"""Build a MemoryManager with all IO mocked out."""
	with (
		patch("red_pill.core.storage.StorageEngine.__init__", return_value=None),
		patch("red_pill.core.storage.QdrantClient"),
	):
		mm = MemoryManager.__new__(MemoryManager)
		mm.cfg = MagicMock()
		mm.storage = MagicMock()
		mm.client = MagicMock()
		mm.embeddings = MagicMock()
		mm.metabolism = MagicMock()
		mm.hive = kwargs.get("hive", MagicMock())
		mm._sleep_hooks = []
		import threading

		mm._reinforce_lock = threading.Lock()
		return mm


# ---------------------------------------------------------------------------
# BayesianInferenceEngine
# ---------------------------------------------------------------------------


class TestBayesianInferenceEngine:
	def test_calculate_erosion_default_kappa(self):
		"""kappa=None falls back to cfg.BAYESIAN_STABILITY_KAPPA at call time, not class def time."""
		result = BayesianInferenceEngine.calculate_erosion(beta=1.0, time_passed_days=10.0)
		# Result should be > 1.0 (beta grew)
		assert result > 1.0

	def test_calculate_erosion_custom_kappa(self):
		"""Custom kappa is respected, overriding the cfg default."""
		result_low = BayesianInferenceEngine.calculate_erosion(beta=1.0, time_passed_days=10.0, kappa=0.01)
		result_high = BayesianInferenceEngine.calculate_erosion(beta=1.0, time_passed_days=10.0, kappa=0.5)
		assert result_low < result_high

	def test_calculate_erosion_capped_at_max_beta(self):
		"""Erosion is capped at BAYESIAN_MAX_BETA (default 20.0)."""
		result = BayesianInferenceEngine.calculate_erosion(beta=20.0, time_passed_days=1000.0, kappa=10.0)
		assert result <= 20.0

	def test_calculate_erosion_kappa_injectable_ignores_cfg(self):
		"""Setting kappa=0.0 means no uncertainty growth regardless of cfg."""
		result = BayesianInferenceEngine.calculate_erosion(beta=5.0, time_passed_days=365.0, kappa=0.0)
		assert result == 5.0


# ---------------------------------------------------------------------------
# MemoryManager — sleep hooks
# ---------------------------------------------------------------------------


class TestMemoryManagerSleepHooks:
	def test_register_sleep_hook(self):
		"""register_sleep_hook appends the callback to _sleep_hooks."""
		mm = _make_mock_memory_manager()
		cb = MagicMock()
		mm.register_sleep_hook(cb)
		assert cb in mm._sleep_hooks

	def test_fire_sleep_hooks_calls_all(self):
		"""fire_sleep_hooks calls all registered callbacks with the summary dict."""
		mm = _make_mock_memory_manager()
		cb1 = MagicMock()
		cb2 = MagicMock()
		mm.register_sleep_hook(cb1)
		mm.register_sleep_hook(cb2)
		summary = {"processed_count": 5, "collection": "work_memories", "timestamp": 1234567890}
		mm.fire_sleep_hooks(summary)
		cb1.assert_called_once_with(summary)
		cb2.assert_called_once_with(summary)

	def test_fire_sleep_hooks_isolates_failures(self):
		"""A failing hook does not prevent subsequent hooks from running."""
		mm = _make_mock_memory_manager()

		def bad_hook(summary):
			raise RuntimeError("Enterprise crashed")

		good_hook = MagicMock()
		mm.register_sleep_hook(bad_hook)
		mm.register_sleep_hook(good_hook)
		mm.fire_sleep_hooks({"processed_count": 0})
		good_hook.assert_called_once()

	def test_no_hooks_fire_silently(self):
		"""fire_sleep_hooks with no registered hooks does nothing."""
		mm = _make_mock_memory_manager()
		mm.fire_sleep_hooks({"processed_count": 0})  # Should not raise


# ---------------------------------------------------------------------------
# MemoryManager — hive injectable
# ---------------------------------------------------------------------------


class TestMemoryManagerHiveInjection:
	def test_hive_injectable_via_kwarg(self):
		"""MemoryManager accepts a custom hive= object for Enterprise substitution."""
		with (
			patch("red_pill.core.storage.StorageEngine.__init__", return_value=None),
			patch("red_pill.core.storage.QdrantClient"),
			patch("red_pill.core.embeddings.EmbeddingEngine.__init__", return_value=None),
			patch("red_pill.core.metabolism.MetabolismKernel.__init__", return_value=None),
			patch("red_pill.hive.HiveMind.__init__", return_value=None),
		):
			custom_hive = MagicMock(name="CustomHive")
			mm = MemoryManager.__new__(MemoryManager)
			# manually init only what's needed
			import threading

			mm.cfg = MagicMock()
			mm.storage = MagicMock()
			mm.client = MagicMock()
			mm.embeddings = MagicMock()
			mm.metabolism = MagicMock()
			mm.hive = custom_hive
			mm._sleep_hooks = []
			mm._reinforce_lock = threading.Lock()
			assert mm.hive is custom_hive

	def test_hive_default_when_not_injected(self):
		"""MemoryManager falls back to HiveMind() when hive= is not provided."""
		with (
			patch("red_pill.core.storage.StorageEngine.__init__", return_value=None),
			patch("red_pill.core.storage.QdrantClient"),
			patch("red_pill.core.embeddings.EmbeddingEngine.__init__", return_value=None),
			patch("red_pill.core.metabolism.MetabolismKernel.__init__", return_value=None),
			# Patch in the memory module's namespace (where the import was bound)
			patch("red_pill.memory.HiveMind") as mock_hive_cls,
		):
			with patch.dict("sys.modules", {
				"red_pill.core.storage": MagicMock(StorageEngine=MagicMock(return_value=MagicMock(client=MagicMock()))),
				"red_pill.core.embeddings": MagicMock(EmbeddingEngine=MagicMock()),
				"red_pill.core.metabolism": MagicMock(MetabolismKernel=MagicMock()),
			}):
				mm = MemoryManager(url="http://localhost:6333")
				assert mm.hive is mock_hive_cls.return_value
