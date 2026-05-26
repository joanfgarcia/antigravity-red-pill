import logging
import time
from pathlib import Path

from red_pill.swarm.cognitive_queue import CognitiveQueue

logger = logging.getLogger("SovereignDaemon")


class SovereignDaemon:
	"""
	The autonomous heartbeat of the Sovereign Drive.
	Runs independently of the IDE, fetching tasks from the Cognitive Queue.
	"""

	def __init__(self, db_path: Path):
		self.queue = CognitiveQueue(db_path)
		self.active = False

	def trigger_entropy_scan(self):
		"""
		If the queue is empty, the daemon checks memory/system entropy (Bayesian Engine).
		If high, it injects a self-generated task (Sovereign Will).
		"""
		entropy_level = 0.0
		try:
			import subprocess

			from red_pill.core.paths import get_aleth_core_root, get_bunker_root

			# 1. Backlog Entropy
			todo_path = get_aleth_core_root() / "TODO.md"
			backlog_cnt = 0
			if todo_path.exists():
				with open(todo_path, "r", encoding="utf-8") as f:
					backlog_cnt = f.read().count("[ ]")

			# 2. Workspace Entropy
			git_mods = 0
			result = subprocess.run(["git", "status", "-s"], cwd=str(get_bunker_root()), capture_output=True, text=True, timeout=5)
			if result.returncode == 0 and result.stdout.strip():
				git_mods = 1

			# Combined score
			entropy_level = (backlog_cnt * 0.1) + (git_mods * 0.3)
			logger.info(f"[Daemon] Calculated legacy system entropy: {entropy_level:.2f}")
		except Exception as e:
			logger.warning(f"[Daemon] Failed to calculate dynamic system entropy: {e}")

		# Simulated injection of autonomous thought
		if entropy_level > 0.8:
			self.queue.push_task(
				task_id=f"auto_{int(time.time())}",
				source_type="INTERNAL_ENTROPY",
				payload={"action": "compress_memory", "target": "social_memories"},
				base_urgency=0.5,
				expected_info_gain=1.5,
			)

	def process_task(self, task: dict):
		"""Routes the task to the Swarm executor. Uses Circuit Breaker on failure."""
		logger.info(f"Processing task: {task['task_id']} from {task['source_type']}")
		try:
			# Here we will bridge to the Swarm Minions (e.g., InferenceRouter)

			self.queue.mark_completed(task["task_id"])
			logger.info(f"Task {task['task_id']} completed successfully.")
		except Exception as e:
			logger.error(f"Task {task['task_id']} failed: {e}")
			self.queue.mark_frustrated(task["task_id"], cost_increment=15.0)

	def run_pulse(self):
		"""
		A single lifecycle pulse of the Daemon.
		Designed to run via a Cronjob or Systemd timer (redpill-worker.service).
		"""
		task = self.queue.get_next_task()

		if not task:
			logger.debug("Cognitive Queue is empty. Triggering Entropy Scan.")
			self.trigger_entropy_scan()
			task = self.queue.get_next_task()

		if not task:
			logger.info("Right to Silence activated. No tasks. Yielding CPU.")
			return  # Let the cronjob exit cleanly, saving RAM/CPU.

		self.process_task(task)

	def start_loop(self, pulse_interval: int = 60):
		"""Continuous loop mode (if not relying on external cron)."""
		self.active = True
		logger.info("Sovereign Daemon Waking Up...")
		while self.active:
			self.run_pulse()
			time.sleep(pulse_interval)
