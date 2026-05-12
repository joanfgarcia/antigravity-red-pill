import logging
import os
import shutil
import subprocess
from typing import Any, Dict

import psutil

from red_pill.core.providers import BaseTelemetryProvider

logger = logging.getLogger(__name__)


class HardwareSentinel(BaseTelemetryProvider):
	"""
	Real-time hardware telemetry for the Red Pill Kernel.
	Monitors CPU, GPU (Nvidia/AMD), and placeholders for NPU.
	"""

	@staticmethod
	def _get_bar(percent: float, length: int = 10) -> str:
		filled = int(length * percent / 100)
		bar = "█" * filled + "░" * (length - filled)
		return f"[{bar}] {percent}%"

	def get_stats(self) -> Dict[str, Any]:
		# CPU Temperature (Linux-only, graceful fallback)
		cpu_temp = None
		if hasattr(psutil, "sensors_temperatures"):
			temps = psutil.sensors_temperatures()
			for chip in ["k10temp", "coretemp", "acpitz"]:
				if chip in temps and temps[chip]:
					cpu_temp = temps[chip][0].current
					break

		stats: Dict[str, Any] = {
			"cpu": {
				"usage_percent": psutil.cpu_percent(interval=None),
				"count": psutil.cpu_count(logical=True),
				"load_avg": os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0),
				"temp": cpu_temp,
			},
			"memory": {
				"total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
				"available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
				"percent": psutil.virtual_memory().percent,
			},
			"gpu": [],
			"npu": {"status": "Undetected"},
			"power": {"battery_percent": None, "ac_online": True},
		}

		# Battery & Power Logic
		if hasattr(psutil, "sensors_battery"):
			battery = psutil.sensors_battery()
			if battery:
				stats["power"]["battery_percent"] = round(battery.percent, 1)
				stats["power"]["ac_online"] = battery.power_plugged

		# NVIDIA GPU Logic (CUDA)
		if shutil.which("nvidia-smi"):
			try:
				cmd = ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
				output = subprocess.check_output(cmd).decode("utf-8").strip().split("\n")
				for gpu_line in output:
					nv_name, nv_util, nv_temp, nv_mem_used, nv_mem_total = gpu_line.split(", ")
					stats["gpu"].append(
						{
							"name": nv_name,
							"type": "CUDA",
							"usage": float(nv_util),
							"temp": float(nv_temp),
							"memory": f"{nv_mem_used}/{nv_mem_total} MB",
						}
					)
			except Exception:
				pass

		# AMD GPU Logic (Native sysfs for ROCm/HIP)
		try:
			# Find amdgpu card and hwmon
			amdgpu_card = None
			for i in range(5):
				card_path = f"/sys/class/drm/card{i}"
				usage_path = os.path.join(card_path, "device/gpu_busy_percent")
				if os.path.exists(usage_path):
					amdgpu_card = card_path
					break

			if amdgpu_card:
				usage = 0
				temp = 0.0

				# Usage
				usage_path = os.path.join(amdgpu_card, "device/gpu_busy_percent")
				if os.path.exists(usage_path):
					with open(usage_path, "r") as f:
						usage = int(float(f.read().strip()))

				# Temperature (Search hwmon)
				for h in range(15):
					h_path = f"/sys/class/hwmon/hwmon{h}"
					if os.path.exists(h_path):
						with open(os.path.join(h_path, "name"), "r") as f:
							if "amdgpu" in f.read():
								with open(os.path.join(h_path, "temp1_input"), "r") as tf:
									temp = float(tf.read().strip()) / 1000.0
								break

				# VRAM
				try:
					with open(os.path.join(amdgpu_card, "device/mem_info_vram_used"), "r") as f:
						gpu_mem_used = int(f.read().strip()) // (1024 * 1024)
					with open(os.path.join(amdgpu_card, "device/mem_info_vram_total"), "r") as f:
						gpu_mem_total = int(f.read().strip()) // (1024 * 1024)
				except Exception:
					gpu_mem_used = 0
					gpu_mem_total = 0

				stats["gpu"].append(
					{
						"name": "AMD Radeon (iGPU)",
						"type": "ROCm",
						"usage": usage,
						"temp": temp,
						"memory": f"{gpu_mem_used}/{gpu_mem_total} MB",
						"status": "Active",
					}
				)
		except Exception:
			# Fallback if sysfs restricted
			if os.path.exists("/sys/class/drm/renderD128"):
				stats["gpu"].append({"name": "AMD Radeon (iGPU)", "type": "ROCm", "status": "Ready", "memory": "N/A"})

		# Ryzen AI NPU
		if os.path.exists("/sys/class/accel/accel0"):
			stats["npu"] = {"name": "Ryzen AI", "type": "NPU", "status": "Ready", "path": "/dev/accel0"}

		return stats

	def compute_delta(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
		"""Calculates the consumed VRAM and CPU load delta."""

		# VRAM Delta (Sum across all GPUs)
		def _get_vram(stats):
			total_used = 0
			for g in stats.get("gpu", []):
				mem = g.get("memory", "0/0 MB")
				try:
					used = int(mem.split("/")[0])
					total_used += used
				except Exception:
					continue
			return total_used

		vram_before = _get_vram(before)
		vram_after = _get_vram(after)

		return {
			"vram_delta_mb": vram_after - vram_before,
			"cpu_usage_start": before["cpu"]["usage_percent"],
			"cpu_usage_end": after["cpu"]["usage_percent"],
		}

	def log_event(self, event_type: str, data: Dict[str, Any]):
		"""Log an event for auditing (v6.8 Hardening)."""
		logger.info(f"[SENTINEL-EVENT] type={event_type} data={data}")


# Create a singleton instance
sentinel = HardwareSentinel()


def get_telemetry_report() -> str:
	"""Generates a Markdown report for the IDE Control Panel."""
	stats = sentinel.get_stats()

	report = "### 🖥️ RED PILL HARDWARE CONTROL PANEL\n\n"

	# CPU/RAM
	cpu_temp_str = f" @ {stats['cpu']['temp']}°C" if stats["cpu"].get("temp") is not None else ""
	report += (
		f"[CPU] {stats['cpu']['usage_percent']}%{cpu_temp_str} | RAM: {stats['memory']['percent']}% ({stats['memory']['available_gb']}GB free)\n"
	)

	# GPU
	if stats["gpu"]:
		for g in stats["gpu"]:
			lbl = g.get("type", "GPU")
			mem_info = f" ({g['memory']})" if "memory" in g else ""
			if "temp" in g:
				report += f"[{lbl}] {g['name']}: {g['usage']}% @ {g['temp']}°C{mem_info}\n"
			else:
				report += f"[{lbl}] {g['name']}: {g['status']}{mem_info}\n"
	else:
		report += "[CUDA/ROCm] Not detected.\n"

	# NPU
	report += f"[NPU] {stats['npu'].get('name', 'NPU')}: {stats['npu']['status']}\n"

	# Power
	pwr = stats.get("power", {})
	if pwr.get("battery_percent") is not None:
		ac_status = "🔌 AC" if pwr["ac_online"] else "🔋 BATTERY"
		report += f"[POWER] {pwr['battery_percent']}% ({ac_status})\n"

	# Memory Queue

	try:
		from red_pill.core.queue_manager import MemoryQueueManager
		from red_pill.memory import MemoryManager

		# Process Queue Status
		pending = MemoryQueueManager().get_pending_count()
		if pending >= 0:
			report += f"\n[MEMORY QUEUE] {pending} pending engrams\n"

		# Process Signal Status
		mgr = MemoryManager()
		count_result = mgr.client.count(collection_name="signal_memories")
		sig_count = count_result.count
		if sig_count >= 0:
			report += f"[SYSTEM SIGNALS] {sig_count} unread warnings/alerts active\n"

		# Process Minion Inbox Status
		try:
			from red_pill.core.inbox import MinionInbox

			inbox_msgs = len(MinionInbox().get_unread(limit=1000))
			if inbox_msgs >= 0:
				report += f"[MINION INBOX] {inbox_msgs} unread background reports\n"
		except Exception:
			pass

	except Exception:
		pass

	return report


def get_cortex_status() -> dict:
	"""Returns a pure JSON-serializable dict of the full Cortex state (Phase 1 V6.9)."""
	import red_pill.config as cfg
	from red_pill.core.inbox import MinionInbox
	from red_pill.core.queue_manager import MemoryQueueManager
	from red_pill.identity import get_default_emotion, get_hedonic_set_point
	from red_pill.memory import MemoryManager
	from red_pill.utils.tone_analyzer import ToneAnalyzer

	stats = sentinel.get_stats()

	# Immutable system stats
	system_status = {
		"cpu": stats.get("cpu", {}),
		"memory": stats.get("memory", {}),
		"gpu": stats.get("gpu", []),
		"npu": stats.get("npu", {}),
		"power": stats.get("power", {}),
	}

	# Immune & Queues
	immune_status = {"memory_queue_pending": 0, "active_signals": [], "minion_inbox_unread": 0}

	metabolism_status: Dict[str, Any] = {"collections": {}, "last_sleep": 0.0}

	try:
		immune_status["memory_queue_pending"] = MemoryQueueManager().get_pending_count()
		immune_status["minion_inbox_unread"] = len(MinionInbox().get_unread(limit=1000))

		mgr = MemoryManager()
		# Fetch active signals
		sig_result = mgr.client.scroll(collection_name="signal_memories", limit=100)
		condensed_signals = []
		for s in sig_result[0]:
			if s.payload:
				condensed_signals.append(
					{
						"name": s.payload.get("name", "unknown"),
						"intensity": s.payload.get("intensity", 0.0),
						"emotion": s.payload.get("emotion", "neutral"),
					}
				)
		immune_status["active_signals"] = condensed_signals

		# Collection sizes
		for coll in cfg.PERMANENT_COLLECTIONS + cfg.BAYESIAN_COLLECTIONS + ["social_memories", "story_memories", "interaction_memories"]:
			try:
				metabolism_status["collections"][coll] = mgr.client.count(collection_name=coll).count
			except Exception:
				pass
	except Exception:
		pass

	# Read sleep state
	try:
		import json
		import os

		if os.path.exists(cfg.METABOLISM_STATE_FILE):
			with open(cfg.METABOLISM_STATE_FILE, "r") as f:
				state = json.loads(f.read().strip())
				if isinstance(state, dict):
					metabolism_status["last_sleep"] = state.get("last_run", 0.0)
				else:
					metabolism_status["last_sleep"] = float(state)
	except Exception:
		pass

	# Identity
	try:
		current_mood = ToneAnalyzer.get_dominant_mood()
	except Exception:
		current_mood = "neutral"

	identity_status = {"hedonic_set_point": get_hedonic_set_point(), "default_emotion": get_default_emotion(), "current_mood": current_mood}

	return {"system": system_status, "immune_system": immune_status, "metabolism": metabolism_status, "identity": identity_status}
