import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

# Add src to pythonpath so it can run independently
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from red_pill.config import IA_DIR, get_config
from red_pill.core.inbox import MinionInbox
from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.telemetry import sentinel

cfg = get_config()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bunker_telemetry")

BUNKER_STATE_FILE = Path(cfg.RUNTIME_DIR) / "bunker_state.json"
TELEMETRY_INTERVAL = 10.0  # seconds


class BunkerTelemetry:
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
		logger.info("Shutting down Bunker Telemetry Task...")
		self.running = False
		if BUNKER_STATE_FILE.exists():
			try:
				BUNKER_STATE_FILE.unlink()
			except Exception:
				pass
		sys.exit(0)

	async def write_state(self):
		self.state["timestamp"] = time.time()

		# v6.2.2: Merciful Merge (pick up updates from interceptor_rp)
		# We preserve all keys NOT managed by the daemon's polling loop.
		managed_keys = {"nvidia", "minions", "swarm", "signals", "timestamp"}
		try:
			if BUNKER_STATE_FILE.exists():
				with open(BUNKER_STATE_FILE, "r") as f:
					disk_state = json.load(f)
				for k, v in disk_state.items():
					if k not in managed_keys:
						self.state[k] = v
		except Exception as merge_err:
			logger.warning(f"Failed to merge disk state: {merge_err}")

		tmp_file = BUNKER_STATE_FILE.with_suffix(".tmp")
		try:
			# Atomic write
			with open(tmp_file, "w") as f:
				json.dump(self.state, f)
			tmp_file.replace(BUNKER_STATE_FILE)

			# Write Markdown LED panel for IDE passive injection
			rule_dir = Path.home() / ".gemini" / "antigravity" / "rules"
			rule_dir.mkdir(parents=True, exist_ok=True)

			# Defensive access for LED panel
			nv = self.state.get("nvidia")
			if not isinstance(nv, dict):
				nv = {}

			raw_minions = self.state.get("minions")
			minions = raw_minions.get("unread", 0) if isinstance(raw_minions, dict) else 0

			raw_signals = self.state.get("signals")
			signals = raw_signals.get("active", 0) if isinstance(raw_signals, dict) else 0

			raw_swarm = self.state.get("swarm")
			swarm_msgs = raw_swarm.get("messages", 0) if isinstance(raw_swarm, dict) else 0

			last_int = self.state.get("last_interaction", 0)

			time_info = ""
			if last_int > 0:
				ago = int(time.time() - last_int)
				time_info = f"\n- **Last Interaction**: {ago}s ago"

			md_content = f"""<bunker_led_panel>
You are actively receiving this telemetry via IDE rule injection (`00_bunker_telemetry.md`).
- **GPU**: {nv.get("status", "offline")} | {nv.get("temp", "N/A")} | VRAM: {nv.get("vram", "N/A")}{time_info}
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

	async def report_pain(self, message: str):
		"""Log a system pain signal to Qdrant (Cortex)."""
		try:
			from red_pill.memory import MemoryManager

			mgr = MemoryManager()
			mgr.add_memory(
				collection="signal_memories",
				text=f"[BunkerTelemetry] {message}",
				importance=0.9,
				emotion="pain",
				color="red",
				metadata={"source": "bunker_daemon", "type": "system_failure"},
			)
			logger.info(f"Pain signal recorded: {message}")
		except Exception as e:
			logger.error(f"Failed to record pain signal: {e}")

	async def poll_telemetry(self, oneshot: bool = False):
		"""Heavy polling loop: runs nvidia-smi with timeout and checks SQLite sizes."""
		while self.running:
			t0 = time.time()

			# 1. Hardware Sentinel
			try:
				# We expect HardwareSentinel to use check_output with a timeout
				# Let's wrap it in to_thread just in case
				stats = await asyncio.to_thread(sentinel.get_stats)
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

			if oneshot:
				break

			elapsed = time.time() - t0
			sleep_time = max(0.1, TELEMETRY_INTERVAL - elapsed)
			await asyncio.sleep(sleep_time)


async def main():
	import argparse

	parser = argparse.ArgumentParser(description="Bünker Daemon (Telemetry & Queue Manager)")
	parser.add_argument("--oneshot", action="store_true", help="Perform a single poll and exit")
	args = parser.parse_args()

	telemetry = BunkerTelemetry()
	daemon = telemetry  # Alias for backward compat if needed in this scope

	if args.oneshot:
		logger.info("Executing Bünker Telemetry Oneshot...")
		try:
			await daemon.poll_telemetry(oneshot=True)
		except Exception as e:
			await daemon.report_pain(f"Telemetry failed: {e}")
			sys.exit(1)

		logger.info("Oneshot complete. Exiting.")
		return

	signal.signal(signal.SIGINT, daemon.shutdown)
	signal.signal(signal.SIGTERM, daemon.shutdown)

	logger.info("Bünker Telemetry Task Started (BE WATER).")
	logger.info("Core 1: Async Polling (Telemetry/Nvidia/Qdrant)")

	try:
		await daemon.poll_telemetry()
	except asyncio.CancelledError:
		pass
	finally:
		logger.info("Daemon gracefully exiting.")


if __name__ == "__main__":
	asyncio.run(main())
