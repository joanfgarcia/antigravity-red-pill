import json
import socket
import subprocess
from typing import Any, Dict

import psutil
import requests

import red_pill.config as cfg
from red_pill.swarm.base import Minion
from red_pill.telemetry import HardwareSentinel


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
		results: Dict[str, Any] = {"status": "optimal", "checks": [], "qdrant_online": False, "npu_status": "Undetected"}

		# 1. Qdrant HTTP & Container Check

		try:
			headers = {}
			if cfg.QDRANT_API_KEY:
				headers["api-key"] = cfg.QDRANT_API_KEY
			# Qdrant v1.x uses root / for health/version check
			resp = requests.get(cfg.QDRANT_URL, headers=headers, timeout=2)
			results["qdrant_online"] = resp.status_code == 200

			# Container status sub-check
			engine = cfg.CONTAINER_ENGINE or "podman"
			try:
				container_proc = subprocess.run(
					[engine, "ps", "--filter", "name=qdrant", "--format", "{{.Status}}"], capture_output=True, text=True, timeout=2
				)
				c_status = container_proc.stdout.strip() or "NOT FOUND"
				results["checks"].append({"component": f"Qdrant ({cfg.CONTAINER_ENGINE})", "status": c_status})
			except Exception as e:
				results["checks"].append({"component": f"Qdrant ({cfg.CONTAINER_ENGINE})", "status": "CMD_ERROR", "details": str(e)})

			results["checks"].append({"component": "Qdrant API", "status": "UP" if results["qdrant_online"] else "DOWN"})
		except Exception:
			results["checks"].append({"component": "Qdrant API", "status": "UNREACHABLE"})



		usage = psutil.disk_usage("/")
		results["checks"].append({"component": "Disk Storage", "status": f"{usage.percent}% used", "free_gb": round(usage.free / (1024**3), 2)})

		# 4. NPU Latent Sentinel Check (v5.3.0)

		stats = HardwareSentinel.get_stats()
		npu_info = stats.get("npu", {})
		if npu_info.get("status") == "Ready":
			results["npu_status"] = "Active"
			results["checks"].append({"component": "Latent Sentinel (NPU)", "status": "ONLINE", "details": f"Unit: {npu_info.get('name', 'N/A')}"})
		else:
			results["checks"].append({"component": "Latent Sentinel (NPU)", "status": "OFFLINE", "details": "NPU not found or driver missing"})

		# 5. Local Healer Protocol (v5.3.0)
		if task == "heal" and results["npu_status"] == "Active":
			from red_pill.memory import MemoryManager

			manager = MemoryManager()
			# Simulating NPU-offloaded sanitation
			manager.sanitize("social_memories", dry_run=False)
			manager.sanitize("work_memories", dry_run=False)
			results["checks"].append(
				{"component": "Healing Engine", "status": "COMPLETED", "details": "NPU-accelerated semantic sanitation executed."}
			)

		if not results["qdrant_online"]:
			results["status"] = "degraded"

		return results
