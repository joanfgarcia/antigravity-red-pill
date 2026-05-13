import logging
import time
from pathlib import Path

from red_pill.swarm.cognitive_queue import CognitiveQueue

# from red_pill.swarm.routing import InferenceRouter

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
        # Placeholder for actual Bayesian entropy calculation (e.g. from procedural_memories)
        entropy_level = 0.0

        # Simulated injection of autonomous thought
        if entropy_level > 0.8:
            self.queue.push_task(
                task_id=f"auto_{int(time.time())}",
                source_type="INTERNAL_ENTROPY",
                payload={"action": "compress_memory", "target": "social_memories"},
                base_urgency=0.5,
                expected_info_gain=1.5
            )

    def process_task(self, task: dict):
        """Routes the task to the Swarm executor. Uses Circuit Breaker on failure."""
        logger.info(f"Processing task: {task['task_id']} from {task['source_type']}")
        try:
            # Here we will bridge to the Swarm Minions (e.g., InferenceRouter)
            # result = InferenceRouter.execute(task['payload'])

            self.queue.mark_completed(task['task_id'])
            logger.info(f"Task {task['task_id']} completed successfully.")
        except Exception as e:
            logger.error(f"Task {task['task_id']} failed: {e}")
            self.queue.mark_frustrated(task['task_id'], cost_increment=15.0)

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
            return # Let the cronjob exit cleanly, saving RAM/CPU.

        self.process_task(task)

    def start_loop(self, pulse_interval: int = 60):
        """Continuous loop mode (if not relying on external cron)."""
        self.active = True
        logger.info("Sovereign Daemon Waking Up...")
        while self.active:
            self.run_pulse()
            time.sleep(pulse_interval)
