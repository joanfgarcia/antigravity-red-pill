import logging
import time

from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.memory import MemoryManager


def report_pain(message: str):
	"""Log a system pain signal to Qdrant (Cortex)."""
	try:
		mgr = MemoryManager()
		mgr.add_memory(
			collection="signal_memories",
			text=f"[QueueWorker] {message}",
			importance=0.8,
			emotion="pain",
			color="orange",
			metadata={"source": "queue_worker", "type": "task_failure"},
		)
		logger.info(f"Pain signal recorded: {message}")
	except Exception as e:
		logger.error(f"Failed to record pain signal: {e}")


logger = logging.getLogger("bunker_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run_queue_worker(poll_interval: int = 5, oneshot: bool = False):
	"""
	Background daemon that consumes the SQLite memory queue
	and slowly offloads them to Qdrant/LLM without blocking
	the main Agent API.
	"""
	logger.info("Starting Bünker Asynchronous Memory Queue Worker...")
	queue = MemoryQueueManager()

	try:
		memory = MemoryManager()
	except Exception as e:
		logger.error(f"Queue Worker failed to init MemoryManager (Qdrant down?): {e}")
		return

	while True:
		try:
			items = queue.dequeue_pending(limit=10)
			for item in items:
				logger.info(f"Processing queued memory {item['id']} (Prompt: {item['prompt'][:20]}...).")
				queue.update_status(item["id"], "processing")
				try:
					uid = memory.record_interaction_pair(prompt=item["prompt"], response=item["response"], role=item["role"], category=item.get("category", "mixed"))
					queue.update_status(item["id"], "completed")
					logger.info(f"Memory {item['id']} successfully ingested. (ID: {uid})")
				except Exception as ingest_error:
					logger.error(f"Memory {item['id']} ingestion failed: {ingest_error}")
					queue.update_status(item["id"], "error")

			if not items:
				if oneshot:
					logger.info("No pending items. Oneshot complete.")
					break
				time.sleep(poll_interval)
			elif oneshot:
				# Check if there are more items after the first batch
				if queue.get_pending_count() == 0:
					logger.info("All pending items processed. Oneshot complete.")
					break

		except KeyboardInterrupt:
			logger.info("Terminating Queue Worker.")
			break
		except Exception as e:
			logger.error(f"Queue worker loop error: {e}")
			report_pain(str(e))
			if oneshot:
				break
			time.sleep(poll_interval)


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="Bünker Memory Queue Worker")
	parser.add_argument("--oneshot", action="store_true", help="Process pending items and exit")
	args = parser.parse_args()

	run_queue_worker(oneshot=args.oneshot)
