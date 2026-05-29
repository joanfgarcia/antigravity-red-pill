"""
Sentinel Plugin: SIP (Sovereign Inference Proxy) — llama-server health.

Specific checks when running:
1. /health endpoint responsiveness
2. Stuck inference detection (high CPU + unresponsive to requests)
"""

import urllib.error
import urllib.request
from typing import Any, List, Optional

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.service_base import ServiceSentinelPlugin

HEALTH_TIMEOUT_S = 3
INFERENCE_TEST_TIMEOUT_S = 5
CPU_STUCK_THRESHOLD = 200.0
MODEL_LOAD_GRACE_S = 180  # 3 minutes grace for model loading after boot


class SipCheck(ServiceSentinelPlugin):
	@property
	def name(self) -> str:
		return "SIP (Sovereign Inference Proxy)"

	@property
	def service_unit(self) -> str:
		return "redpill-llm.service"

	@property
	def config_key(self) -> Optional[str]:
		return "SIP_ENABLED"

	def audit_health(self, cfg: Any) -> List[AuditFinding]:
		findings = []

		port = self._find_llama_port()
		if not port:
			findings.append(
				AuditFinding(
					type="sip_unhealthy",
					severity=5.0,
					message=f"{self.name}: service is active but no llama-server port detected.",
					metadata={"service": self.service_unit},
				)
			)
			return findings

		# Health endpoint
		health_ok = False
		try:
			resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=HEALTH_TIMEOUT_S)
			if resp.status == 200:
				health_ok = True
		except urllib.error.HTTPError as he:
			# Server responds but not healthy (e.g. 503 "Loading model")
			# Grace period: model loading is normal during first ~3 min after boot
			uptime_s = self._get_service_uptime()
			if uptime_s is not None and uptime_s < MODEL_LOAD_GRACE_S:
				import logging
				logging.getLogger(__name__).info(
					f"[{self.name}] HTTP {he.code} on port {port} — "
					f"within grace period ({uptime_s:.0f}s / {MODEL_LOAD_GRACE_S}s). Letting it load."
				)
			else:
				uptime_str = f"{uptime_s:.0f}s" if uptime_s is not None else "unknown"
				findings.append(
					AuditFinding(
						type="sip_loading",
						severity=6.0,
						message=(
							f"{self.name}: /health returned HTTP {he.code} on port {port} "
							f"(stuck loading, uptime: {uptime_str} > {MODEL_LOAD_GRACE_S}s grace)."
						),
						metadata={"service": self.service_unit, "port": port, "http_code": he.code, "uptime_s": uptime_s},
					)
				)
		except Exception as e:
			findings.append(
				AuditFinding(
					type="sip_unhealthy",
					severity=7.0,
					message=f"{self.name}: /health endpoint unresponsive on port {port}: {e}",
					metadata={"service": self.service_unit, "port": port},
				)
			)

		# Stuck inference: high CPU + can't process requests
		if health_ok:
			cpu_pct = self._get_llama_cpu()
			if cpu_pct > CPU_STUCK_THRESHOLD and self._is_inference_stuck(port):
				findings.append(
					AuditFinding(
						type="sip_stuck",
						severity=9.0,
						message=f"{self.name}: llama-server stuck in inference loop (CPU: {cpu_pct:.0f}%, port {port}).",
						metadata={"service": self.service_unit, "port": port, "cpu_pct": cpu_pct},
					)
				)

		return findings

	def heal_specific(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Restart the LLM service and evaporate any stale pain signals."""
		healed = self._restart_service()
		if healed:
			try:
				from red_pill.memory import MemoryManager
				mm = MemoryManager()
				mm.evaporate_signals("hypervisor_unreachable")
			except Exception:
				pass
		return healed

	# ── Specific helpers ──

	def _find_llama_port(self) -> int | None:
		import subprocess

		try:
			result = subprocess.run(["pgrep", "-a", "llama-server"], capture_output=True, text=True, timeout=5)
			for line in result.stdout.splitlines():
				parts = line.split()
				for i, part in enumerate(parts):
					if part == "--port" and i + 1 < len(parts):
						return int(parts[i + 1])
		except Exception:
			pass
		return None

	def _get_llama_cpu(self) -> float:
		import subprocess

		try:
			result = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True, timeout=5)
			total_cpu = 0.0
			for pid in result.stdout.strip().splitlines():
				ps_result = subprocess.run(["ps", "-p", pid.strip(), "-o", "%cpu", "--no-headers"], capture_output=True, text=True, timeout=5)
				try:
					total_cpu += float(ps_result.stdout.strip().replace(",", "."))
				except ValueError:
					pass
			return total_cpu
		except Exception:
			return 0.0

	def _is_inference_stuck(self, port: int) -> bool:
		import json

		req_data = json.dumps(
			{
				"model": "test",
				"messages": [{"role": "user", "content": "OK"}],
				"max_tokens": 1,
			}
		).encode()
		req = urllib.request.Request(
			f"http://127.0.0.1:{port}/v1/chat/completions", data=req_data, headers={"Content-Type": "application/json"}, method="POST"
		)
		try:
			urllib.request.urlopen(req, timeout=INFERENCE_TEST_TIMEOUT_S)
			return False
		except Exception:
			return True

	def _get_service_uptime(self) -> float | None:
		"""Returns seconds since the service entered 'active' state, or None if unknown."""
		import subprocess
		from datetime import datetime, timezone

		try:
			result = subprocess.run(
				["systemctl", "--user", "show", self.service_unit, "--property=ActiveEnterTimestamp"],
				capture_output=True, text=True, timeout=5,
			)
			# Output: ActiveEnterTimestamp=Fri 2026-05-29 12:03:30 CEST
			line = result.stdout.strip()
			if "=" not in line:
				return None
			ts_str = line.split("=", 1)[1].strip()
			if not ts_str:
				return None
			# Parse systemd timestamp (locale-aware, use subprocess for safety)
			ts_result = subprocess.run(
				["date", "-d", ts_str, "+%s"],
				capture_output=True, text=True, timeout=5,
			)
			epoch = float(ts_result.stdout.strip())
			now = datetime.now(timezone.utc).timestamp()
			return max(0.0, now - epoch)
		except Exception:
			return None
