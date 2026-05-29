"""
Sentinel Plugin: Qdrant Vector DB.

Core service (config_key=None → always required).
Specific checks: HTTP reachability of the Qdrant endpoint.
"""

import subprocess
import urllib.error
import urllib.request
from typing import Any, List

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.service_base import ServiceSentinelPlugin


class QdrantCheck(ServiceSentinelPlugin):
	@property
	def name(self) -> str:
		return "Qdrant Vector DB"

	@property
	def service_unit(self) -> str:
		return "qdrant.service"

	# config_key = None → always required (inherited default)

	def audit_health(self, cfg: Any) -> List[AuditFinding]:
		findings = []
		try:
			url = getattr(cfg, "QDRANT_URL", "http://localhost:6333")
			urllib.request.urlopen(url, timeout=2)
		except Exception as e:
			if not isinstance(e, urllib.error.HTTPError):
				findings.append(AuditFinding(
					type="amnesia",
					severity=10.0,
					message=f"{self.name}: Vector DB is UNREACHABLE at {getattr(cfg, 'QDRANT_URL', 'unknown')}",
					metadata={"service": self.service_unit}
				))
		return findings
