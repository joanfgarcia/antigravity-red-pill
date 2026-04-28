#!/usr/bin/env python3
"""
oneiromancy_pulse.py — Semantic Threading Engine.

Iteratively triggers MemoryManager.dream() on a collection to forge
semantic axons between nodes.
"""

import argparse
import logging
import time

from red_pill.memory import MemoryManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("oneiromancy_pulse")


def main():
	parser = argparse.ArgumentParser(description="Run a Dream Cycle (Oneiromancy) on a Bünker collection.")
	parser.add_argument("--collection", type=str, default="archive_memories", help="Target collection.")
	parser.add_argument("--limit", type=int, default=50, help="Points per dream batch.")
	parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between batches.")
	parser.add_argument("--duration", type=int, default=300, help="Total duration in seconds to run the pulse.")
	args = parser.parse_args()

	mem = MemoryManager()
	start_time = time.time()

	logger.info(f"Starting Oneiromancy Pulse on '{args.collection}' for {args.duration}s...")

	total_synapses = 0
	while time.time() - start_time < args.duration:
		try:
			result = mem.dream(collection=args.collection, limit=args.limit)
			if result.get("status") == "ok":
				synapses = result.get("synapses", 0)
				total_synapses += synapses
				if synapses > 0:
					logger.info(f"Dream batch complete. Synapses forged: {synapses}")
			elif result.get("status") == "empty":
				logger.info("No more memories to dream. Pulse complete.")
				break
			else:
				logger.warning(f"Dream error: {result.get('message')}")

			time.sleep(args.sleep)
		except Exception as e:
			logger.error(f"Pulse iteration failed: {e}")
			time.sleep(10)

	logger.info(f"Oneiromancy Pulse finished. Total synapses forged: {total_synapses}")


if __name__ == "__main__":
	main()
