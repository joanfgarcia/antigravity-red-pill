"""
Autonomous Task Executor — Executes cognitive queue tasks via agy CLI.

Uses the same AgyBridge pattern: `agy -p --dangerously-skip-permissions`
connecting to the local Antigravity IDE LanguageServer. No API key needed.

Entry point for systemd-run spawned subprocesses from SovereignDaemon.
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from red_pill.core.paths import get_log_dir

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("TaskExecutor")


def load_task(db_path: Path, task_id: str) -> dict:
	with sqlite3.connect(db_path) as conn:
		conn.row_factory = sqlite3.Row
		cursor = conn.execute("SELECT * FROM cognitive_tasks WHERE task_id = ?", (task_id,))
		row = cursor.fetchone()
		if not row:
			raise ValueError(f"Task {task_id} not found in database {db_path}")
		return dict(row)


def execute_task(db_path: Path, task_id: str):
	"""Execute a task using the AgyBridge (agy CLI)."""
	task = load_task(db_path, task_id)
	payload = json.loads(task["payload"]) if isinstance(task["payload"], str) else task["payload"]
	objective = payload.get("objective") or payload.get("action")

	logger.info(f"Starting execution of task {task_id}...")
	logger.info(f"Objective: {objective}")

	# Create task-specific log file in standard XDG log directory
	task_log_dir = get_log_dir() / "tasks"
	task_log_dir.mkdir(parents=True, exist_ok=True)
	task_log_path = task_log_dir / f"{task_id}.log"

	# Configure a file handler for task logs
	fh = logging.FileHandler(task_log_path, encoding="utf-8")
	fh.setLevel(logging.INFO)
	fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
	logging.getLogger("").addHandler(fh)

	try:
		# Use the configured agent bridge — same pattern as Telegram/AWAKENING
		from red_pill.swarm.bridges import create_bridge

		bridge = create_bridge()
		caps = bridge.get_capabilities()
		logger.info(f"Bridge: {caps.backend.value.upper()} (auto_approve={caps.auto_approve})")

		# Build prompt with headless restrictions
		prompt = (
			'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
			"[SYSTEM: AUTONOMOUS TASK EXECUTOR]\n"
			"1. PROHIBITED: You are STRICTLY FORBIDDEN from using the `run_command` tool unless the task explicitly requires it.\n"
			"2. PERMITTED: Use file tools (write_to_file, replace_file_content) and MCP RedPill-Kernel tools.\n"
			"3. CONTEXT: This is an autonomous background task. The user is NOT present. Be concise.\n"
			"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
			f"[AUTONOMOUS TASK: {task_id}]\n"
			f"Execute the following objective:\n{objective}\n"
		)

		result = bridge.prompt(prompt, timeout=1500)

		if result.ok:
			logger.info("Agent finished execution successfully.")
			logger.info(f"Agent Response:\n{result.response}")
			print(result.response)
		else:
			logger.error(f"Agent returned error: {result.error}")
			raise RuntimeError(f"Agent execution failed: {result.error}")

	except Exception as e:
		logger.exception(f"Exception occurred during agent execution: {e}")
		raise
	finally:
		logging.getLogger("").removeHandler(fh)
		fh.close()


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Autonomous background task executor")
	parser.add_argument("--task-id", required=True, help="ID of the task to execute")
	parser.add_argument("--db-path", required=True, help="Path to the SQLite task queue database")
	args = parser.parse_args()

	try:
		execute_task(Path(args.db_path), args.task_id)
	except Exception as e:
		logger.error(f"Executor failed: {e}")
		sys.exit(1)
