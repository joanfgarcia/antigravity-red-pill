"""
Sentinel Plugin: Neon-Link Telegram Bridge.

Specific checks when running:
- HTTP reachability of the bridge endpoint (NEON_LINK_URL)
"""

import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, List, Optional

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.service_base import ServiceSentinelPlugin


class NeonLinkCheck(ServiceSentinelPlugin):
	@property
	def name(self) -> str:
		return "Neon-Link Telegram Bridge"

	@property
	def service_unit(self) -> str:
		return "neon-link.service"

	@property
	def config_key(self) -> Optional[str]:
		return "NEON_LINK_ENABLED"

	def audit_health(self, cfg: Any) -> List[AuditFinding]:
		findings = []
		try:
			urllib.request.urlopen(cfg.NEON_LINK_URL, timeout=2)
		except Exception as e:
			if not isinstance(e, urllib.error.HTTPError):
				findings.append(
					AuditFinding(
						type="neon_hung",
						severity=10.0,
						message=f"{self.name}: bridge is HUNG/OFFLINE at {cfg.NEON_LINK_URL}: {e}",
						metadata={"service": self.service_unit, "url": cfg.NEON_LINK_URL},
					)
				)
		return findings

	def heal_specific(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Neon-Link fallback: try systemd restart, then pkill + start.sh."""
		if self._restart_service():
			return True

		# Fallback: manual restart via start.sh
		try:
			subprocess.run(["pkill", "-f", "neon-link"], check=False)
			from red_pill.core.paths import get_bunker_root

			neon_dir = str(get_bunker_root().parent / "neon-link")
			start_script = os.path.join(neon_dir, "start.sh")

			if os.path.exists(start_script):
				subprocess.Popen(["nohup", start_script], cwd=neon_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp)
				return True
		except Exception:
			pass
		return False
