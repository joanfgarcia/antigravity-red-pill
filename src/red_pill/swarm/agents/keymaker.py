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
			"daemon_online": False
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

		if not results["qdrant_online"] or not results["daemon_online"]:
			results["status"] = "degraded"

		return results
