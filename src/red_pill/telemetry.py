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
				temp = 0
				
				# Usage
				usage_path = os.path.join(amdgpu_card, "device/gpu_busy_percent")
				if os.path.exists(usage_path):
					with open(usage_path, "r") as f:
						usage = float(f.read().strip())
				
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
				mem_used = 0
				mem_total = 0
				try:
					with open(os.path.join(amdgpu_card, "device/mem_info_vram_used"), "r") as f:
						mem_used = int(f.read().strip()) // (1024*1024)
					with open(os.path.join(amdgpu_card, "device/mem_info_vram_total"), "r") as f:
						mem_total = int(f.read().strip()) // (1024*1024)
				except:
					pass
				
				stats["gpu"].append({
					"name": "AMD Radeon (iGPU)",
					"type": "ROCm",
					"usage": usage,
					"temp": temp,
					"memory": f"{mem_used}/{mem_total} MB",
					"status": "Active"
				})
		except Exception:
			# Fallback if sysfs restricted
			if os.path.exists("/sys/class/drm/renderD128"):
				stats["gpu"].append({"name": "AMD Radeon", "type": "ROCm", "status": "Ready", "memory": "N/A"})

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
			mem_info = f" ({g['memory']})" if "memory" in g else ""
			if "temp" in g:
				report += f"[{lbl}] {g['name']}: {g['usage']}% @ {g['temp']}°C{mem_info}\n"
			else:
				report += f"[{lbl}] {g['name']}: {g['status']}{mem_info}\n"
	else:
		report += "[CUDA/ROCm] Not detected.\n"

	# NPU
	report += f"[NPU] {stats['npu'].get('name', 'NPU')}: {stats['npu']['status']}\n"

	return report
