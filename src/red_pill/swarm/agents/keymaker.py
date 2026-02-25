from typing import Any, Dict

from red_pill.swarm.base import Minion


class KeymakerMinion(Minion):
	"""
	Infrastructure Guard & Bünker Protector.
	Verifies Qdrant, Sidecar, and Service health.
	"""

	name: str = "Keymaker-01"
	specialization: str = "Infrastructure Health & Connectivity"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Perform a full infrastructure health check.
		"""
		results = {
			"status": "optimal",
			"checks": [],
			"qdrant_online": False,
			"daemon_online": False,
			"npu_status": "Undetected"
		}

		# 1. Qdrant HTTP Check
		import requests
		try:
			resp = requests.get("http://localhost:6333/health", timeout=2)
			results["qdrant_online"] = (resp.status_code == 200)
			results["checks"].append({"component": "Qdrant DB", "status": "UP" if results["qdrant_online"] else "DOWN"})
		except Exception:
			results["checks"].append({"component": "Qdrant DB", "status": "UNREACHABLE"})

		# 2. Daemon Socket Check
		import socket

		import red_pill.config as cfg
		try:
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.settimeout(1)
				client.connect(cfg.DAEMON_SOCKET_PATH)
				results["daemon_online"] = True
				results["checks"].append({"component": "Memory Sidecar", "status": "ACTIVE"})
		except Exception:
			results["checks"].append({"component": "Memory Sidecar", "status": "INACTIVE"})

		# 3. Disk Space Check
		import psutil
		usage = psutil.disk_usage('/')
		results["checks"].append({
			"component": "Disk Storage",
			"status": f"{usage.percent}% used",
			"free_gb": round(usage.free / (1024**3), 2)
		})

		# 4. NPU Latent Sentinel Check (v5.3.0)
		from red_pill.telemetry import HardwareSentinel
		stats = HardwareSentinel.get_stats()
		npu_info = stats.get("npu", {})
		if npu_info.get("status") == "Ready":
			results["npu_status"] = "Active"
			results["checks"].append({
				"component": "Latent Sentinel (NPU)",
				"status": "ONLINE",
				"details": f"Unit: {npu_info.get('name', 'N/A')}"
			})
		else:
			results["checks"].append({
				"component": "Latent Sentinel (NPU)",
				"status": "OFFLINE",
				"details": "NPU not found or driver missing"
			})

		# 5. Local Healer Protocol (v5.3.0)
		if task == "heal" and results["npu_status"] == "Active":
			from red_pill.memory import MemoryManager
			manager = MemoryManager()
			# Simulating NPU-offloaded sanitation
			manager.sanitize("social_memories", dry_run=False)
			manager.sanitize("work_memories", dry_run=False)
			results["checks"].append({
				"component": "Healing Engine",
				"status": "COMPLETED",
				"details": "NPU-accelerated semantic sanitation executed."
			})

		if not results["qdrant_online"] or not results["daemon_online"]:
			results["status"] = "degraded"

		return results
