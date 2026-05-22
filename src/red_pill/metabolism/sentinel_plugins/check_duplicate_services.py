"""
Service Health Guard — Sentinel Plugin.

Reads the Service Health Contract manifest (services.yaml) and
auto-configures monitoring for each service:
- daemon-loop:     health endpoint + duplicate detection
- daemon-listener: health endpoint + duplicate detection
- oneshot:         not monitored here (systemd TimeoutStartSec handles it)

Also detects runaway CPU and memory bloat for all active daemons.
"""

import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from red_pill.core.service_contract import ServiceContract, load_manifest
from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

# CPU / Memory thresholds (applied to all daemons)
CPU_THRESHOLD_PCT = 50.0
MEMORY_LIMIT_MB = 500


class ServiceHealthCheck(SentinelPlugin):
	"""
	Unified sentinel plugin: duplicates, hung services, CPU, memory.
	Driven entirely by the services.yaml manifest.
	"""

	@property
	def name(self) -> str:
		return "Service Health Guard"

	def is_enabled(self, cfg: Any) -> bool:
		return True

	# ── helpers ──────────────────────────────────────────────

	def _unit_state(self, unit: str) -> Optional[str]:
		try:
			r = subprocess.run(
				["systemctl", "--user", "is-active", unit],
				capture_output=True, text=True, timeout=5,
			)
			return r.stdout.strip()
		except Exception:
			return None

	def _is_enabled(self, unit: str) -> bool:
		try:
			r = subprocess.run(
				["systemctl", "--user", "is-enabled", unit],
				capture_output=True, text=True, timeout=5,
			)
			return r.stdout.strip() == "enabled"
		except Exception:
			return False

	def _get_unit_cpu(self, unit: str) -> float:
		try:
			r = subprocess.run(
				["systemctl", "--user", "show", unit, "--property=MainPID"],
				capture_output=True, text=True, timeout=5,
			)
			main_pid = 0
			for line in r.stdout.splitlines():
				if line.startswith("MainPID="):
					main_pid = int(line.split("=", 1)[1])
			if main_pid <= 0:
				return 0.0

			total_cpu = 0.0
			for flag in ["-p", "--ppid"]:
				ps = subprocess.run(
					["ps", flag, str(main_pid), "-o", "%cpu", "--no-headers"],
					capture_output=True, text=True, timeout=5,
				)
				for line in ps.stdout.splitlines():
					try:
						total_cpu += float(line.strip().replace(",", "."))
					except ValueError:
						pass
			return total_cpu
		except Exception:
			return 0.0

	def _get_unit_rss_mb(self, unit: str) -> float:
		try:
			r = subprocess.run(
				["systemctl", "--user", "show", unit, "--property=MemoryCurrent"],
				capture_output=True, text=True, timeout=5,
			)
			for line in r.stdout.splitlines():
				if line.startswith("MemoryCurrent="):
					val = line.split("=", 1)[1].strip()
					if val and val != "[not set]":
						return int(val) / (1024 * 1024)
			return 0.0
		except Exception:
			return 0.0

	# ── audit ────────────────────────────────────────────────

	def audit(self, cfg: Any) -> List[AuditFinding]:
		findings: List[AuditFinding] = []
		contracts: Dict[str, ServiceContract] = load_manifest()

		if not contracts:
			findings.append(AuditFinding(
				type="config_missing",
				severity=3.0,
				message="Service manifest (services.yaml) not found or empty. Cannot audit services.",
			))
			return findings

		for name, contract in contracts.items():
			if contract.type == "oneshot":
				continue  # systemd TimeoutStartSec handles these

			unit = contract.unit
			state = self._unit_state(unit)

			# 1. DUPLICATE DETECTION
			for alias in contract.legacy_aliases:
				alias_state = self._unit_state(alias)
				alias_enabled = self._is_enabled(alias)

				if alias_state == "active" or alias_enabled:
					both_active = alias_state == "active" and state == "active"
					severity = 9.0 if both_active else 5.0
					state_str = "RUNNING" if alias_state == "active" else "ENABLED (dormant)"
					findings.append(AuditFinding(
						type="duplicate_service",
						severity=severity,
						message=(
							f"Legacy service '{alias}' is {state_str} alongside "
							f"canonical '{unit}'. Causes duplicate pollers."
						),
						metadata={"legacy": alias, "canonical": unit},
					))

			# Skip remaining checks if service isn't active
			if state != "active":
				continue

			# 2. HEALTH ENDPOINT (daemon-loop and daemon-listener)
			if contract.health_url:
				try:
					urllib.request.urlopen(contract.health_url, timeout=5)
				except Exception as e:
					if not isinstance(e, urllib.error.HTTPError):
						findings.append(AuditFinding(
							type="hung_service",
							severity=9.0,
							message=(
								f"Service '{unit}' is active but health endpoint "
								f"'{contract.health_url}' is UNREACHABLE: {e}"
							),
							metadata={"service": unit, "url": contract.health_url},
						))

			# 3. STUCK 'activating' STATE
			if state == "activating":
				findings.append(AuditFinding(
					type="hung_service",
					severity=8.0,
					message=f"Service '{unit}' stuck in 'activating' state (boot loop).",
					metadata={"service": unit},
				))

			# 4. RUNAWAY CPU
			cpu = self._get_unit_cpu(unit)
			if cpu > CPU_THRESHOLD_PCT:
				findings.append(AuditFinding(
					type="runaway_cpu",
					severity=7.0,
					message=f"Service '{unit}' consuming {cpu:.1f}% CPU (threshold: {CPU_THRESHOLD_PCT:.0f}%).",
					metadata={"service": unit, "cpu_pct": cpu},
				))

			# 5. MEMORY BLOAT
			rss = self._get_unit_rss_mb(unit)
			if rss > MEMORY_LIMIT_MB:
				findings.append(AuditFinding(
					type="memory_bloat",
					severity=6.0,
					message=f"Service '{unit}' using {rss:.0f} MB RSS (limit: {MEMORY_LIMIT_MB} MB).",
					metadata={"service": unit, "rss_mb": rss},
				))

		return findings

	# ── heal ─────────────────────────────────────────────────

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		meta = finding.metadata or {}

		if finding.type == "duplicate_service":
			legacy = meta.get("legacy")
			if not legacy:
				return False
			try:
				subprocess.run(["systemctl", "--user", "stop", legacy], check=False, timeout=10)
				subprocess.run(["systemctl", "--user", "disable", legacy], check=False, timeout=10)
				subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, timeout=10)
				return True
			except Exception:
				return False

		if finding.type in ("hung_service", "runaway_cpu"):
			service = meta.get("service")
			if not service:
				return False
			try:
				subprocess.run(["systemctl", "--user", "restart", service], check=False, timeout=15)
				return True
			except Exception:
				return False

		return False
