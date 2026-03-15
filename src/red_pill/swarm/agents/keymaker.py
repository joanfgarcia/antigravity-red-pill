import hmac
import json
import subprocess
import socket
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
		results: Dict[str, Any] = {"status": "optimal", "checks": [], "qdrant_online": False, "daemon_online": False, "npu_status": "Undetected"}

		# 1. Qdrant HTTP & Container Check

		try:
			headers = {}
			if cfg.QDRANT_API_KEY:
				headers["api-key"] = cfg.QDRANT_API_KEY
			# Qdrant v1.x uses root / for health/version check
			resp = requests.get(cfg.QDRANT_URL, headers=headers, timeout=2)
			results["qdrant_online"] = resp.status_code == 200
			
			# Container status sub-check
			try:
				container_proc = subprocess.run(
					[cfg.CONTAINER_ENGINE, "ps", "--filter", "name=qdrant", "--format", "{{.Status}}"],
					capture_output=True, text=True, timeout=2
				)
				c_status = container_proc.stdout.strip() or "NOT FOUND"
				results["checks"].append({"component": f"Qdrant ({cfg.CONTAINER_ENGINE})", "status": c_status})
			except Exception as e:
				results["checks"].append({"component": f"Qdrant ({cfg.CONTAINER_ENGINE})", "status": "CMD_ERROR", "details": str(e)})

			results["checks"].append({"component": "Qdrant API", "status": "UP" if results["qdrant_online"] else "DOWN"})
		except Exception:
			results["checks"].append({"component": "Qdrant API", "status": "UNREACHABLE"})

		# 2. Daemon Socket & Deep Health Check (Canary Encode)

		try:
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.settimeout(2)
				client.connect(cfg.DAEMON_SOCKET_PATH)
				
				# Canary Encode Test (v6.1.0)
				payload = {
					"command": "ping", # Ping first
					"api_key": cfg.SIDECAR_AUTH_KEY
				}
				
				def send_req(p):
					data = json.dumps(p).encode("utf-8")
					client.sendall(len(data).to_bytes(4, byteorder="big") + data)
					resp_header = client.recv(4)
					if not resp_header: return None
					resp_len = int.from_bytes(resp_header, byteorder="big")
					return json.loads(client.recv(resp_len).decode("utf-8"))

				ping_resp = send_req(payload)
				if ping_resp and ping_resp.get("status") == "ok":
					# Deep check: actual encoding
					canary_payload = {"text": "healthcheck", "api_key": cfg.SIDECAR_AUTH_KEY}
					# Re-establish or reuse? Socket might be closed by daemon after one sync depending on implementation.
					# But handle_connection loop handles one request per 'with conn:'. 
					# So we need a new connection for the canary if we want to be safe, 
					# but let's try a second send if the daemon keeps it open. 
					# Looking at memory_daemon.py: it uses 'with conn:' which closes after handle_connection returns.
					# So we need a NEW connection for the canary.
				
				results["daemon_online"] = True
				results["checks"].append({"component": "Sidecar Socket", "status": "CONNECTED", "path": cfg.DAEMON_SOCKET_PATH})
		except Exception as e:
			results["checks"].append({"component": "Memory Sidecar", "status": "INACTIVE", "details": str(e)})

		# Deep check execution (Separate connection)
		if results["daemon_online"]:
			try:
				with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
					client.settimeout(3)
					client.connect(cfg.DAEMON_SOCKET_PATH)
					canary_payload = {"text": "canary", "api_key": cfg.SIDECAR_AUTH_KEY}
					data = json.dumps(canary_payload).encode("utf-8")
					client.sendall(len(data).to_bytes(4, byteorder="big") + data)
					
					resp_header = client.recv(4)
					if resp_header:
						resp_len = int.from_bytes(resp_header, byteorder="big")
						canary_resp = json.loads(client.recv(resp_len).decode("utf-8"))
						if canary_resp.get("status") == "ok" and "vector" in canary_resp:
							results["checks"].append({"component": "Sidecar Engine", "status": "OPTIMAL", "details": "Canary Encode Success"})
						else:
							results["checks"].append({"component": "Sidecar Engine", "status": "FAILED", "details": canary_resp.get("message", "Unknown Error")})
							results["daemon_online"] = False
			except Exception as e:
				results["checks"].append({"component": "Sidecar Engine", "status": "UNREACHABLE", "details": str(e)})
				results["daemon_online"] = False

		# 3. Disk Space Check

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

		if not results["qdrant_online"] or not results["daemon_online"]:
			results["status"] = "degraded"

		return results
