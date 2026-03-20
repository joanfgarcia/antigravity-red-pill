import os
import shutil
import subprocess
from typing import Any, Dict

import psutil


class HardwareSentinel:
	"""
	Real-time hardware telemetry for the Red Pill Kernel.
	Monitors CPU, GPU (Nvidia/AMD), and placeholders for NPU.
	"""

	@staticmethod
	def _get_bar(percent: float, length: int = 10) -> str:
		filled = int(length * percent / 100)
		bar = "█" * filled + "░" * (length - filled)
		return f"[{bar}] {percent}%"

	@staticmethod
	def get_stats() -> Dict[str, Any]:
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
				"load_avg": os.getloadavg(),
				"temp": cpu_temp,
			},
			"memory": {
				"total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
				"available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
				"percent": psutil.virtual_memory().percent,
			},
			"gpu": [],
			"npu": {"status": "Undetected"},
		}

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
				stats["gpu"].append({"name": "AMD Radeon", "type": "ROCm", "status": "Ready", "memory": "N/A"})

		# Ryzen AI NPU
		if os.path.exists("/sys/class/accel/accel0"):
			stats["npu"] = {"name": "Ryzen AI", "type": "NPU", "status": "Ready", "path": "/dev/accel0"}

		return stats


def get_telemetry_report() -> str:
	"""Generates a Markdown report for the IDE Control Panel."""
	stats = HardwareSentinel.get_stats()

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
