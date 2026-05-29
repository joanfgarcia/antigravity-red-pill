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
		self.db_path = db_path
		self.queue = CognitiveQueue(db_path)
		self.active = False

	def trigger_entropy_scan(self):
		"""
		If the queue is empty, the daemon checks memory/system entropy (Bayesian Engine).
		If high, it injects a self-generated task (Sovereign Will).
		"""
		# Call DriveEvaluator._scrape_context() as instructed to replace/retrieve context
		try:
			from red_pill.cognitive.drive_evaluator import DriveEvaluator

			evaluator = DriveEvaluator(None)  # type: ignore[arg-type]
			context_data = evaluator._scrape_context()
			logger.info(f"[Daemon] Scraped context for entropy scan:\n{context_data}")
		except Exception as e:
			logger.warning(f"[Daemon] Failed to scrape context via DriveEvaluator: {e}")

		entropy_level = 0.0
		try:
			import math
			import subprocess

			from red_pill.cognitive.drive_evaluator import DriveEvaluator
			from red_pill.core.paths import get_aleth_core_root, get_bunker_root, get_state_dir

			# 1. Backlog Entropy: Cantidad de tareas [ ] pendientes en TODO.md (cada tarea añade 0.2 de entropía)
			todo_path = get_aleth_core_root() / "TODO.md"
			backlog_cnt = 0
			if todo_path.exists():
				with open(todo_path, "r", encoding="utf-8") as f:
					backlog_cnt = f.read().count("[ ]")
			backlog_entropy = backlog_cnt * 0.2

			# 2. Workspace Entropy: Presencia de ficheros modificados localmente (git status -s añade 0.3 de entropía)
			git_mods = 0
			result = subprocess.run(["git", "status", "-s"], cwd=str(get_bunker_root()), capture_output=True, text=True, timeout=5)
			if result.returncode == 0 and result.stdout.strip():
				git_mods = 1
			workspace_entropy = git_mods * 0.3

			# 3. Temporal Decay: Tiempo transcurrido desde la última interacción (decaimiento hedónico FSRS)
			activity_file = get_state_dir() / "last_user_activity.txt"
			if activity_file.exists():
				mtime = activity_file.stat().st_mtime
				hours_idle = (time.time() - mtime) / 3600.0
				stability_days = 0.5
				time_passed_days = hours_idle / 24.0
				r = math.exp(math.log(0.9) * (time_passed_days / stability_days))
				temporal_decay = 1.0 - r
			else:
				temporal_decay = 1.0

			# Combined score
			entropy_level = backlog_entropy + workspace_entropy + temporal_decay
			logger.info(
				f"[Daemon] Calculated system entropy: {entropy_level:.2f} "
				f"(backlog: {backlog_entropy:.2f}, workspace: {workspace_entropy:.2f}, temporal_decay: {temporal_decay:.2f})"
			)
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
			import subprocess
			import sys

			# Calculate limits (baseline of 10G limit as safe fallback)
			mem_limit = "10G"

			# Build command to run under systemd-run with cgroup containment
			cmd = [
				"systemd-run",
				"--user",
				"--scope",
				"-p",
				f"MemoryMax={mem_limit}",
				sys.executable,
				"-m",
				"red_pill.swarm.executor",
				"--task-id",
				task["task_id"],
				"--db-path",
				str(self.db_path),
			]

			logger.info(f"[Daemon] Spawning background executor under systemd-run: {' '.join(cmd)}")

			# Enforce 30-minute timeout (1800 seconds)
			result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

			if result.returncode != 0:
				raise RuntimeError(f"Executor exited with code {result.returncode}.\nStdout: {result.stdout}\nStderr: {result.stderr}")

			self.queue.mark_completed(task["task_id"])
			logger.info(f"Task {task['task_id']} completed successfully.")
		except subprocess.TimeoutExpired:
			logger.error(f"Task {task['task_id']} exceeded execution timeout limit (30 minutes). Terminating.")
			self.queue.mark_frustrated(task["task_id"], cost_increment=15.0)
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
