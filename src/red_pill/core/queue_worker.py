import logging
import time

from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.memory import MemoryManager

logger = logging.getLogger("bunker_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run_queue_worker(poll_interval: int = 5):
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
					uid = memory.record_interaction_pair(prompt=item["prompt"], response=item["response"], role=item["role"])
					queue.update_status(item["id"], "completed")
					logger.info(f"Memory {item['id']} successfully ingested. (ID: {uid})")
				except Exception as ingest_error:
					logger.error(f"Memory {item['id']} ingestion failed: {ingest_error}")
					queue.update_status(item["id"], "error")

			if not items:
				time.sleep(poll_interval)

		except KeyboardInterrupt:
			logger.info("Terminating Queue Worker.")
			break
		except Exception as e:
			logger.error(f"Queue worker loop error: {e}")
			time.sleep(poll_interval)


if __name__ == "__main__":
	run_queue_worker()
