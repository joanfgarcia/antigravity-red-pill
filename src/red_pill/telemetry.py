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
	def get_stats() -> Dict[str, Any]:
		stats = {
			"cpu": {
				"usage_percent": psutil.cpu_percent(interval=None),
				"count": psutil.cpu_count(logical=True),
				"load_avg": os.getloadavg()
			},
			"memory": {
				"total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
				"available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
				"percent": psutil.virtual_memory().percent
			},
			"gpu": [],
			"npu": {"status": "Undetected"}
		}

		# NVIDIA GPU Logic (CUDA)
		if shutil.which("nvidia-smi"):
			try:
				cmd = ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
				output = subprocess.check_output(cmd).decode("utf-8").strip().split("\n")
				for line in output:
					name, util, temp, mem_used, mem_total = line.split(", ")
					stats["gpu"].append({
						"name": name,
						"type": "CUDA",
						"usage": float(util),
						"temp": float(temp),
						"memory": f"{mem_used}/{mem_total} MB"
					})
			except Exception:
				pass

		# AMD GPU Logic (ROCm)
		if os.path.exists("/sys/class/drm/renderD128"):
			# Stub for ROCm detection
			stats["gpu"].append({
				"name": "AMD Radeon",
				"type": "ROCm",
				"status": "Ready"
			})

		# Ryzen AI NPU
		if os.path.exists("/sys/class/accel/accel0"):
			stats["npu"] = {
				"name": "Ryzen AI",
				"type": "NPU",
				"status": "Ready",
				"path": "/dev/accel0"
			}

		return stats

def get_telemetry_report() -> str:
	"""Generates a Markdown report for the IDE Control Panel."""
	stats = HardwareSentinel.get_stats()

	report = "### 🖥️ RED PILL HARDWARE CONTROL PANEL\n\n"

	# CPU/RAM
	report += f"[CPU] {stats['cpu']['usage_percent']}% | RAM: {stats['memory']['percent']}% ({stats['memory']['available_gb']}GB free)\n"

	# GPU
	if stats["gpu"]:
		for g in stats["gpu"]:
			lbl = g.get("type", "GPU")
			if "temp" in g:
				report += f"[{lbl}] {g['name']}: {g['usage']}% @ {g['temp']}°C ({g['memory']})\n"
			else:
				report += f"[{lbl}] {g['name']}: {g['status']}\n"
	else:
		report += "[CUDA/ROCm] Not detected.\n"

	# NPU
	report += f"[NPU] {stats['npu'].get('name', 'NPU')}: {stats['npu']['status']}\n"

	return report
