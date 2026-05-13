import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from red_pill.plugins.antigravity_ide.worker import IDEWorker
from red_pill.swarm.daemon import SovereignDaemon


def get_latest_conversation_db() -> Path:
	brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
	latest_db = None
	latest_time = 0

	if not brain_dir.exists():
		print(f"Brain dir {brain_dir} not found.")
		sys.exit(1)

	for conv_dir in brain_dir.iterdir():
		if not conv_dir.is_dir():
			continue
		db_path = conv_dir / "cognitive_queue.db"
		if db_path.exists():
			mtime = db_path.stat().st_mtime
			if mtime > latest_time:
				latest_time = mtime
				latest_db = db_path

	if not latest_db:
		print("No cognitive_queue.db found in any conversation.")
		return None

	return latest_db


if __name__ == "__main__":
	import logging

	logging.basicConfig(level=logging.INFO)
	db_path = get_latest_conversation_db()
	if db_path:
		print(f"[Daemon] Waking up. Target DB: {db_path}")
		daemon = SovereignDaemon(db_path)
		daemon.run_pulse()

	print("[Daemon] Processing IDE Worker Telemetry/Telegram routing...")
	worker = IDEWorker()
	worker.run_once()
