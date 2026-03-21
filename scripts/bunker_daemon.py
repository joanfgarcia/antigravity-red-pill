import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

# Add src to pythonpath so it can run independently
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from red_pill.config import IA_DIR
from red_pill.core.inbox import MinionInbox
from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.telemetry import HardwareSentinel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bunker_daemon")

BUNKER_STATE_FILE = Path("/tmp/bunker_state.json")
TELEMETRY_INTERVAL = 10.0  # seconds


class BunkerDaemon:
	def __init__(self):
		self.running = True
		self.state = {
			"timestamp": 0.0,
			"nvidia": {"status": "offline", "temp": None, "vram": None},
			"minions": {"unread": 0},
			"swarm": {"messages": 0},
			"signals": {"active": 0},
		}

		# Ensure queue manager avoids fastembed lazy loading until needed
		try:
			self.queue_mgr = MemoryQueueManager()
			self.db_path = Path(self.queue_mgr.db_path)
			self.wal_path = Path(str(self.db_path) + "-wal")
		except Exception as e:
			logger.error(f"Failed to init MemoryQueueManager: {e}")
			self.queue_mgr = None
			self.db_path = Path(IA_DIR) / "storage" / "memory_queue.db"
			self.wal_path = Path(str(self.db_path) + "-wal")

	def shutdown(self, sig, frame):
		logger.info("Shutting down Bunker Daemon...")
		self.running = False
		if BUNKER_STATE_FILE.exists():
			try:
				BUNKER_STATE_FILE.unlink()
			except Exception:
				pass
		sys.exit(0)

	async def write_state(self):
		self.state["timestamp"] = time.time()
		tmp_file = BUNKER_STATE_FILE.with_suffix(".tmp")
		try:
			# Atomic write
			with open(tmp_file, "w") as f:
				json.dump(self.state, f)
			tmp_file.replace(BUNKER_STATE_FILE)

			# Write Markdown LED panel for IDE passive injection
			rule_dir = Path.home() / ".gemini" / "antigravity" / "rules"
			rule_dir.mkdir(parents=True, exist_ok=True)
			rule_file = rule_dir / "00_bunker_telemetry.md"
			rule_tmp = rule_file.with_suffix(".tmp")

			nv = self.state.get("nvidia", {})
			minions = self.state.get("minions", {}).get("unread", 0)
			signals = self.state.get("signals", {}).get("active", 0)
			swarm_msgs = self.state.get("swarm", {}).get("messages", 0)

			md_content = f"""<bunker_led_panel>
You are actively receiving this telemetry via IDE rule injection (`00_bunker_telemetry.md`).
- **GPU**: {nv.get("status", "offline")} | {nv.get("temp", "N/A")} | VRAM: {nv.get("vram", "N/A")}
- **Minion Inbox**: {minions} unread background reports
- **Active System Signals (PAIN)**: {signals} active signals
- **Swarm Messages**: {swarm_msgs} pending messages
</bunker_led_panel>
"""
			# 1. Antigravity Global
			ag_dir = Path.home() / ".gemini" / "antigravity" / "rules"
			ag_dir.mkdir(parents=True, exist_ok=True)
			ag_file = ag_dir / "00_bunker_telemetry.md"
			self._atomic_write(ag_file, md_content)

			# 2. Cursor IDE Rule (.mdc)
			cursor_dir = Path(IA_DIR) / ".cursor" / "rules"
			try:
				cursor_dir.mkdir(parents=True, exist_ok=True)
				# Prefix .mdc for Cursor generic context
				cursor_file = cursor_dir / "00_bunker_telemetry.mdc"
				# Cursor rules need some frontmatter usually, but raw markdown is often accepted, or we just write it.
				cursor_content = f"---\ndescription: Red Pill Kernel Live Telemetry\nglobs: *\n---\n\n{md_content}"
				self._atomic_write(cursor_file, cursor_content)
			except Exception:
				pass

			# 3. Generic Fallback in root
			fb_file = Path(IA_DIR) / ".bunker_telemetry.md"
			self._atomic_write(fb_file, md_content)

		except Exception as e:
			logger.error(f"Failed to write state: {e}")

	def _atomic_write(self, target_file: Path, content: str):
		tmp_file = target_file.with_suffix(".tmp_bunker")
		with open(tmp_file, "w") as f:
			f.write(content)
		tmp_file.replace(target_file)

	async def poll_telemetry(self):
		"""Heavy polling loop: runs nvidia-smi with timeout and checks SQLite sizes."""
		while self.running:
			t0 = time.time()

			# 1. Hardware Sentinel
			try:
				# We expect HardwareSentinel to use check_output with a timeout
				# Let's wrap it in to_thread just in case
				stats = await asyncio.to_thread(HardwareSentinel.get_stats)
				gpus = stats.get("gpu", [])
				nvidia = None
				if isinstance(gpus, list):
					for g in gpus:
						if "nvidia" in str(g.get("name", "")).lower() or "rtx" in str(g.get("name", "")).lower():
							nvidia = g
							break
				elif isinstance(gpus, dict):
					nvidia = gpus

				if nvidia and "err" not in nvidia.get("status", "").lower():
					self.state["nvidia"] = {"status": "online", "temp": nvidia.get("temp", "N/A"), "vram": nvidia.get("memory", "N/A")}
				else:
					self.state["nvidia"] = {"status": "offline", "temp": None, "vram": None}
			except Exception as e:
				logger.warning(f"Telemetry hardware poll failed: {e}")

			# 2. Minions Inbox
			try:
				inbox = MinionInbox()
				unread = await asyncio.to_thread(inbox.get_unread, limit=100)
				self.state["minions"]["unread"] = len(unread)
			except Exception:
				pass

			# 3. Signals (From Cortex/Qdrant)
			try:
				from red_pill.memory import MemoryManager

				mgr = MemoryManager()
				count_result = await asyncio.to_thread(mgr.client.count, collection_name="signal_memories")
				self.state["signals"]["active"] = count_result.count
			except Exception:
				pass

			# Commit State
			await self.write_state()

			elapsed = time.time() - t0
			sleep_time = max(0.1, TELEMETRY_INTERVAL - elapsed)
			await asyncio.sleep(sleep_time)

	async def watch_sqlite_queues(self):
		"""Event-driven watcher for the WAL file using watchfiles."""
		try:
			from watchfiles import awatch
		except ImportError:
			logger.warning("watchfiles not installed. Falling back to dumb polling for Queues.")
			await self._fallback_queue_poller()
			return

		logger.info(f"Subscribed to FileSystem events on {self.db_path.parent}...")

		# If queue is not empty at startup, process it
		if self.queue_mgr and self.queue_mgr.get_pending_count() > 0:
			await asyncio.to_thread(self.queue_mgr.process_pending)

		# Watch the directory (inotify limits us watching specific files if they get rotated easily,
		# but watchfiles abstracts it. We watch the directory and filter by WAL).
		async for changes in awatch(self.db_path.parent):
			if not self.running:
				break

			trigger = False
			for change_type, path in changes:
				if "memory_queue.db-wal" in path or "memory_queue.db" in path:
					trigger = True
					break

			if trigger and self.queue_mgr:
				logger.info("Inotify Event: Queue WAL modified. Awakening Memory Worker.")
				# Small debounce to let SQLite finish the OS flush if needed
				await asyncio.sleep(0.1)
				try:
					await asyncio.to_thread(self.queue_mgr.process_pending)
					logger.info("Memory Worker finished draining queue. Back to 0% CPU sleep.")
				except Exception as e:
					logger.error(f"Memory Worker crashed processing queue: {e}")

	async def _fallback_queue_poller(self):
		while self.running:
			if self.queue_mgr and self.queue_mgr.get_pending_count() > 0:
				await asyncio.to_thread(self.queue_mgr.process_pending)
			await asyncio.sleep(2.0)


async def main():
	daemon = BunkerDaemon()
	signal.signal(signal.SIGINT, daemon.shutdown)
	signal.signal(signal.SIGTERM, daemon.shutdown)

	logger.info("Bünker Daemon Started (BE WATER).")
	logger.info("Core 1: Async Polling (Telemetry/Nvidia/Qdrant)")
	logger.info("Core 2: Event-Driven Queue Worker (Inotify/SQLite)")

	try:
		await asyncio.gather(daemon.poll_telemetry(), daemon.watch_sqlite_queues())
	except asyncio.CancelledError:
		pass
	finally:
		logger.info("Daemon gracefully exiting.")


if __name__ == "__main__":
	asyncio.run(main())
