"""
Metabolism Stress Test: Drain Loop Verification Protocol (v6.5.2)
Part of the Red Pill Protocol Sovereign Suite.
"""

import logging
import sys
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

# Dynamic Path Resolution
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR / "src"))

import red_pill.config as cfg  # noqa: E402
from red_pill.metabolism.sleep import perform_sleep_cycle  # noqa: E402

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("STRESS_TEST")


def run_stress_test() -> None:
	"""
	Executes a high-density sleep cycle simulation to verify the
	batch-drain logic introduced in v6.5.1.
	"""
	logger.info("Initializing Metabolism Stress Test (v6.5.2 Drain Loop)...")

	# 1. Mock Memory Manager
	memory_manager = MagicMock()
	client = memory_manager.client

	# 2. Mock Config
	# We force multiple batches: 10 items / 3 limit = 4 batches (3, 3, 3, 1).
	cfg.SLEEP_SCROLL_LIMIT = 3
	cfg.SLEEP_CHUNK_SIZE = 1000
	cfg.SLEEP_CULL_THRESHOLD = 0.5
	cfg.SLEEP_MAX_LLM_FAILURES = 5

	# 3. Create Mock Data
	mock_items = []
	for i in range(10):
		point = MagicMock()
		point.id = f"mock-id-{i}"
		point.payload = {"content": f"USER: Interaction {i}\n\nASSISTANT: Response {i}", "metadata": {"category": "work"}}
		mock_items.append(point)

	# 4. Mock Client Scroll (Yield items in batches)
	# First call: Signal check (empty)
	# Subsequent calls: interaction_memories drain
	side_effects: List[Tuple[list, any]] = [
		([], None),  # Signal check: empty
		(mock_items[0:3], None),
		(mock_items[3:6], None),
		(mock_items[6:9], None),
		(mock_items[9:10], None),
		([], None),
	]
	client.scroll.side_effect = side_effects
	client.collection_exists.return_value = True

	# 5. Patch External Intelligence & Network
	with (
		patch("red_pill.metabolism.sleep._check_llm_available", return_value=True),
		patch("red_pill.metabolism.sleep.distill_engram") as mock_distill,
		patch("red_pill.metabolism.sleep.synthesize_hub") as mock_synth,
	):
		# Set intensity to 0.8 to AVOID culling (threshold is 0.5)
		mock_distill.return_value = {"summary": "Mock summary", "emotion": "joy", "intensity": 0.8}
		mock_synth.return_value = "Mock Master Summary"

		# Execute Sleep Ritual
		logger.info("Starting Sleep Cycle Simulation...")
		processed_count = perform_sleep_cycle(memory_manager)

		logger.info(f"Test Complete. Total Processed: {processed_count}")

		# 6. Verification
		# 10 interactions -> 20 sub-nodes + 10 hubs = 30 points.
		assert processed_count == 30
		assert client.scroll.call_count == 6
		assert client.delete.call_count == 10

	logger.info("✔️ STRESS TEST PASSED: Batched Drain Loop verified.")


if __name__ == "__main__":
	try:
		run_stress_test()
	except AssertionError as e:
		logger.error(f"❌ TEST FAILED: Assertion Error: {e}")
		sys.exit(1)
	except Exception as e:
		logger.error(f"💥 TEST CRASHED: {e}")
		sys.exit(1)
