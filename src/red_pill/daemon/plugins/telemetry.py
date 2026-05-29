"""Telemetry Plugin — GPU, inbox, pain vectors, LED panel (ex bunker_telemetry.py)."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.telemetry")


class TelemetryPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "telemetry"

	@property
	def interval_s(self) -> float:
		return 30.0

	@property
	def timeout_s(self) -> float:
		return 10.0

	async def on_start(self) -> None:
		import red_pill.config as cfg
		from red_pill.core.paths import get_queue_dir

		self._cfg = cfg
		self._state_file = Path(cfg.RUNTIME_DIR) / "bunker_state.json"
		self._state: Dict[str, Any] = {
			"timestamp": 0.0,
			"nvidia": {"status": "offline", "temp": None, "vram": None},
			"minions": {"unread": 0},
			"swarm": {"messages": 0, "events": {"success": 0, "warning": 0, "error": 0}},
			"signals": {"active": 0, "pain_vec": [0, 0, 0]},
		}

		try:
			from red_pill.core.queue_manager import MemoryQueueManager

			self._queue_mgr: Optional[Any] = MemoryQueueManager()
			q_path = getattr(self._queue_mgr, "db_path", None)
			self._db_path = Path(q_path) if q_path else get_queue_dir() / "bunker_queue.db"
		except Exception as e:
			logger.error(f"[TELEMETRY] Failed to init QueueManager: {e}")
			self._queue_mgr = None
			self._db_path = get_queue_dir() / "bunker_queue.db"

	async def on_stop(self) -> None:
		if self._state_file.exists():
			try:
				self._state_file.unlink()
			except Exception:
				pass

	async def tick(self) -> None:
		import asyncio

		# 1. Hardware
		await asyncio.to_thread(self._poll_hardware)
		# 2. Inbox + Swarm traffic light
		await asyncio.to_thread(self._poll_inbox)
		# 3. Signals
		await asyncio.to_thread(self._poll_signals)
		# 4. Write state + LED panels
		await asyncio.to_thread(self._write_state)

	def _poll_hardware(self) -> None:
		try:
			from red_pill.telemetry import sentinel

			stats = sentinel.get_stats()
			gpus = stats.get("gpu", [])
			nvidia = None
			if isinstance(gpus, list):
				for g in gpus:
					name = str(g.get("name", "")).lower()
					if "nvidia" in name or "rtx" in name:
						nvidia = g
						break
			elif isinstance(gpus, dict):
				nvidia = gpus

			if nvidia and "err" not in nvidia.get("status", "").lower():
				self._state["nvidia"] = {
					"status": "online",
					"temp": nvidia.get("temp", "N/A"),
					"vram": nvidia.get("memory", "N/A"),
				}
			else:
				self._state["nvidia"] = {"status": "offline", "temp": None, "vram": None}
		except Exception as e:
			logger.warning(f"[TELEMETRY] Hardware poll failed: {e}")

	def _poll_inbox(self) -> None:
		try:
			from red_pill.core.inbox import MinionInbox

			inbox = MinionInbox()
			unread = inbox.get_unread(limit=100)
			self._state["minions"]["unread"] = len(unread)

			events = {"success": 0, "warning": 0, "error": 0}
			for r in unread:
				status = str(r.get("status", "")).lower()
				if status in ["success", "ok", "done"]:
					events["success"] += 1
				elif status in ["warning", "warn", "partial"]:
					events["warning"] += 1
				elif status in ["error", "fail", "failure", "critical"]:
					events["error"] += 1
			self._state["swarm"]["events"] = events
		except Exception:
			pass

	def _poll_signals(self) -> None:
		try:
			from red_pill.memory import MemoryManager

			mm = MemoryManager()
			count_result = mm.client.count(collection_name="signal_memories")
			self._state["signals"]["active"] = count_result.count

			# Pain vector [T, D, H]
			t_count = self._state["swarm"]["events"].get("error", 0)
			d_count = count_result.count
			nv_state = self._state.get("nvidia", {})
			h_count = 1 if (nv_state.get("temp") or 0) > 80 or nv_state.get("status") == "offline" else 0
			self._state["signals"]["pain_vec"] = [t_count, d_count, h_count]
		except Exception:
			pass

	def _write_state(self) -> None:
		self._state["timestamp"] = time.time()

		# Merciful merge: preserve non-managed keys
		managed_keys = {"nvidia", "minions", "swarm", "signals", "timestamp"}
		try:
			if self._state_file.exists():
				with open(self._state_file, "r") as f:
					disk_state = json.load(f)
				for k, v in disk_state.items():
					if k not in managed_keys:
						self._state[k] = v
		except Exception:
			pass

		# Atomic write state JSON
		tmp = self._state_file.with_suffix(".tmp")
		try:
			with open(tmp, "w") as f:
				json.dump(self._state, f)
			tmp.replace(self._state_file)
		except Exception as e:
			logger.error(f"[TELEMETRY] Failed to write state: {e}")
			return

		# LED panel
		self._write_led_panels()

	def _write_led_panels(self) -> None:
		nv = self._state.get("nvidia") or {}
		minions = self._state.get("minions", {}).get("unread", 0) if isinstance(self._state.get("minions"), dict) else 0
		signals = self._state.get("signals", {}).get("active", 0) if isinstance(self._state.get("signals"), dict) else 0
		swarm_msgs = self._state.get("swarm", {}).get("messages", 0) if isinstance(self._state.get("swarm"), dict) else 0

		last_int = self._state.get("last_interaction", 0.0)
		time_info = ""
		if isinstance(last_int, (int, float)) and last_int > 0:
			ago = int(time.time() - float(last_int))
			time_info = f"\n- **Last Interaction**: {ago}s ago"

		md = f"""<bunker_led_panel>
You are actively receiving this telemetry via IDE rule injection (`00_bunker_telemetry.md`).
- **GPU**: {nv.get("status", "offline")} | {nv.get("temp", "N/A")} | VRAM: {nv.get("vram", "N/A")}{time_info}
- **Minion Inbox**: {minions} unread background reports
- **Active System Signals (PAIN)**: {signals} active signals
- **Swarm Messages**: {swarm_msgs} pending messages
</bunker_led_panel>
"""

		# 1. Antigravity rules
		ag_dir = Path.home() / ".gemini" / "antigravity" / "rules"
		ag_dir.mkdir(parents=True, exist_ok=True)
		self._atomic_write(ag_dir / "00_bunker_telemetry.md", md)

		# 2. Cursor IDE
		try:
			cursor_dir = Path(self._cfg.WORKSPACE_ROOT) / ".cursor" / "rules"
			cursor_dir.mkdir(parents=True, exist_ok=True)
			cursor_md = f"---\ndescription: Red Pill Kernel Live Telemetry\nglobs: *\n---\n\n{md}"
			self._atomic_write(cursor_dir / "00_bunker_telemetry.mdc", cursor_md)
		except Exception:
			pass

		# 3. Workspace root fallback
		self._atomic_write(Path(self._cfg.WORKSPACE_ROOT) / ".bunker_telemetry.md", md)

	def _atomic_write(self, target: Path, content: str) -> None:
		tmp = target.with_suffix(".tmp_bunker")
		try:
			with open(tmp, "w") as f:
				f.write(content)
			tmp.replace(target)
		except Exception:
			pass
