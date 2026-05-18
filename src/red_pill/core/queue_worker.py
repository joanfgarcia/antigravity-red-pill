import asyncio
import logging
import time

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.memory import MemoryManager
from red_pill.swarm.factory import MinionFactory


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


def process_cognitive_tasks(cog_queue: CognitiveQueueManager, oneshot: bool = False):
	"""Process up to 5 DAG tasks from the cognitive queue using the Swarm MinionFactory."""
	for _ in range(5):
		task = cog_queue.pop_next_task()
		if not task:
			break

		logger.info(f"Processing cognitive task {task['id']} from source: {task['source']}")
		try:
			minion = MinionFactory.create(task["source"])
			if not minion:
				raise ValueError(f"MinionFactory failed to create '{task['source']}'")

			payload = task.get("payload", {})

			# Soporte tanto para Minions asíncronos (como Echo) como síncronos
			if asyncio.iscoroutinefunction(minion.execute):
				_ = asyncio.run(minion.execute(**payload))
			else:
				_ = minion.execute(**payload)

			cog_queue.mark_completed(task["id"])
			logger.info(f"Cognitive task {task['id']} completed successfully.")

		except Exception as e:
			cog_queue.mark_failed(task["id"], str(e))
			logger.error(f"Cognitive task {task['id']} failed: {e}")
			report_pain(f"Cognitive Task {task['id']} ({task['source']}) failed: {e}")


def run_queue_worker(poll_interval: int = 5, oneshot: bool = False):
	"""
	Background daemon that consumes the SQLite queues
	and slowly offloads them without blocking the main IDE Agent.
	"""
	logger.info("Starting Bünker Asynchronous Queue Worker (Zero-Daemon)...")
	queue = MemoryQueueManager()

	try:
		cog_queue = CognitiveQueueManager()
	except Exception as e:
		logger.error(f"Queue Worker failed to init CognitiveQueueManager: {e}")
		cog_queue = None

	try:
		memory = MemoryManager()
	except Exception as e:
		logger.error(f"Queue Worker failed to init MemoryManager (Qdrant down?): {e}")
		return

	while True:
		try:
			# 1. Process Cognitive DAG Tasks
			if cog_queue:
				process_cognitive_tasks(cog_queue, oneshot)

			# 2. Process Memory Queue (Fast Buffer -> Qdrant)
			items = queue.dequeue_pending(limit=10)
			for item in items:
				logger.info(f"Processing queued memory {item['id']} (Prompt: {item['prompt'][:20]}...).")
				queue.update_status(item["id"], "processing")
				try:
					uid = memory.record_interaction_pair(
						prompt=item["prompt"], response=item["response"], role=item["role"], category=item.get("category", "mixed")
					)
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

	parser = argparse.ArgumentParser(description="Bünker Asynchronous Queue Worker")
	parser.add_argument("--oneshot", action="store_true", help="Process pending items and exit")
	args = parser.parse_args()

	run_queue_worker(oneshot=args.oneshot)
