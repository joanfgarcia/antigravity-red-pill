"""
ServiceSentinelPlugin — Base class for config-aware service reconciliation.

Pattern:
- config_key=True  + service stopped → finding: service_down  → heal: start
- config_key=True  + service running → delegate to audit_health() for specific checks
- config_key=False + service running → finding: service_unwanted → heal: stop
- config_key=False + service stopped → no findings (desired state)
- config_key=None                   → always audit (core/required service)

Subclasses only implement:
- name (property): human-readable name
- service_unit (property): systemd unit name
- config_key (property, optional): config flag that gates this service
- audit_health(cfg): specific health checks when service is running and enabled
- heal_specific(cfg, finding): optional custom healing (default: restart)
"""

import logging
import subprocess
from abc import abstractmethod
from typing import Any, List, Optional

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

logger = logging.getLogger(__name__)


class ServiceSentinelPlugin(SentinelPlugin):
	"""Config-aware service sentinel with declarative reconciliation."""

	@property
	@abstractmethod
	def service_unit(self) -> str:
		"""Systemd unit name (e.g. 'redpill-llm.service')."""
		...

	@property
	def config_key(self) -> Optional[str]:
		"""Config attribute that gates this service (e.g. 'SIP_ENABLED').
		Return None for always-required services."""
		return None

	# ── Reconciliation engine ─────────────────────────────────

	def is_enabled(self, cfg: Any) -> bool:
		return True  # Always run — reconciliation logic handles everything

	def audit(self, cfg: Any) -> List[AuditFinding]:
		desired_active = self._is_desired_active(cfg)
		is_active = self._is_service_active()

		# ── Disabled + running → unwanted ──
		if not desired_active:
			if is_active:
				return [
					AuditFinding(
						type="service_unwanted",
						severity=5.0,
						message=f"{self.name}: service '{self.service_unit}' is running but {self.config_key}=False. Wasting resources.",
						metadata={"service": self.service_unit, "config_key": self.config_key, "expected": "stopped", "actual": "active"},
					)
				]
			return []

		# ── Enabled + not running → down ──
		if not is_active:
			return [
				AuditFinding(
					type="service_down",
					severity=7.0,
					message=f"{self.name}: service '{self.service_unit}' is not running.",
					metadata={"service": self.service_unit, "expected": "active", "actual": "inactive"},
				)
			]

		# ── Enabled + running → delegate to specific health checks ──
		return self.audit_health(cfg)

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		if finding.type == "service_unwanted":
			return self._stop_service()
		elif finding.type == "service_down":
			return self._start_service()
		else:
			return self.heal_specific(cfg, finding)

	# ── Subclass hooks (override these) ──────────────────────

	@abstractmethod
	def audit_health(self, cfg: Any) -> List[AuditFinding]:
		"""Specific health checks when the service IS running and SHOULD be.
		Return empty list if healthy."""
		...

	def heal_specific(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Custom healing for specific findings. Default: restart."""
		return self._restart_service()

	# ── Service control primitives ────────────────────────────

	def _is_desired_active(self, cfg: Any) -> bool:
		"""Check config to determine if the service should be running."""
		if self.config_key is None:
			return True  # No config key → always required
		val = getattr(cfg, self.config_key, None)
		if val is None:
			import os

			env_val = os.getenv(self.config_key)
			if env_val is not None:
				return env_val.lower() in ("true", "1", "yes")
			return True  # Default to enabled if not configured
		return bool(val)

	def _is_service_active(self) -> bool:
		try:
			r = subprocess.run(
				["systemctl", "--user", "is-active", self.service_unit],
				capture_output=True,
				text=True,
				timeout=5,
			)
			return r.stdout.strip() == "active"
		except Exception:
			return False

	def _start_service(self) -> bool:
		try:
			logger.info(f"[{self.name}] Starting {self.service_unit}")
			subprocess.run(["systemctl", "--user", "start", self.service_unit], check=False, timeout=15)
			return True
		except Exception as e:
			logger.error(f"[{self.name}] Failed to start {self.service_unit}: {e}")
			return False

	def _stop_service(self) -> bool:
		try:
			logger.info(f"[{self.name}] Stopping {self.service_unit} (disabled in config)")
			subprocess.run(["systemctl", "--user", "stop", self.service_unit], check=False, timeout=15)
			return True
		except Exception as e:
			logger.error(f"[{self.name}] Failed to stop {self.service_unit}: {e}")
			return False

	def _restart_service(self) -> bool:
		try:
			logger.info(f"[{self.name}] Restarting {self.service_unit}")
			subprocess.run(["systemctl", "--user", "restart", self.service_unit], check=False, timeout=15)
			return True
		except Exception as e:
			logger.error(f"[{self.name}] Failed to restart {self.service_unit}: {e}")
			return False
