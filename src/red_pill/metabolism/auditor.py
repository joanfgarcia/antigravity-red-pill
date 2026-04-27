"""
Red Pill Sentinel Auditor (v6.6.0-alpha)
The tactical 'Frontal Lobe' for sovereign infrastructure monitoring.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AuditFinding:
	type: str # 'formatting' | 'test' | 'security' | 'pain'
	severity: float # 0.0 - 10.0
	message: str
	metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AuditReport:
	status: str # 'green' | 'yellow' | 'red'
	findings: List[AuditFinding] = field(default_factory=list)
	intensity: float = 0.0

class SentinelAuditor:
	def __init__(self, target_repos: Optional[List[str]] = None):
		self.target_repos = target_repos or []
		self.logger = logging.getLogger("redpill.auditor")
		self.uv_path = os.path.expanduser("~/.local/bin/uv")

	def audit_repo(self, repo_path: str) -> AuditReport:
		"""Run standard sovereign checks on a repository."""
		report = AuditReport(status="green")

		if not os.path.exists(repo_path):
			report.status = "red"
			report.findings.append(AuditFinding(type="infra", severity=10.0, message=f"Path not found: {repo_path}"))
			return report

		# 1. Formatting & Linting (Ruff)
		self.logger.info(f"Auditing formatting for {repo_path}")
		ruff = subprocess.run(
			[self.uv_path, "run", "ruff", "check", "."],
			cwd=repo_path, capture_output=True, text=True
		)
		if ruff.returncode != 0:
			report.status = "yellow"
			report.findings.append(AuditFinding(
				type="formatting",
				severity=5.0,
				message="Ruff check failed",
				metadata={"stdout": ruff.stdout}
			))

		# 2. Testing (Pytest)
		self.logger.info(f"Auditing tests for {repo_path}")
		# Run subset of tests for speed in daily audit if repo is large
		pytest = subprocess.run(
			[self.uv_path, "run", "pytest", "-n", "auto", "--dist", "loadgroup"],
			cwd=repo_path, capture_output=True, text=True
		)
		if pytest.returncode != 0:
			report.status = "red"
			report.findings.append(AuditFinding(
				type="test",
				severity=8.0,
				message="Pytest suite failed",
				metadata={"stdout": pytest.stdout}
			))

		# Calculate global intensity based on findings
		report.intensity = sum(f.severity for f in report.findings)
		if any(f.severity >= 8.0 for f in report.findings):
			report.status = "red"
		elif report.findings:
			report.status = "yellow"

		return report

	def sync_to_thalamus(self, report: AuditReport):
		"""Inject audit findings into social_memories as pain signals."""
		from red_pill.memory import MemoryManager
		manager = MemoryManager()

		self.logger.info(f"Sentinel Analysis complete. Status: {report.status}. Intensity: {report.intensity}")

		for finding in report.findings:
			# 1. Active Pain Signal (Directly visible in fetch_signal_memories / Cortex Status)
			if finding.severity >= 6.0:
				self.logger.warning(f"Active Pain detected: {finding.message}")
				manager.add_memory(
					collection="signal_memories",
					text=f"{finding.type.upper()}_FAILURE: {finding.message}",
					importance=finding.severity,
					metadata={
						"category": "active_pain",
						"signal_type": finding.type,
						"source": "sentinel_auditor"
					},
					intensity=finding.severity,
					color="red",
					emotion="alert"
				)

			# 2. Historical Audit Log (Social/Context memories)
			if finding.severity >= 4.0:
				manager.add_memory(
					collection="social_memories",
					text=f"[SENTINEL_PAIN] {finding.type.upper()}: {finding.message}",
					importance=finding.severity,
					metadata={
						"category": "audit_finding_history",
						"signal_type": finding.type,
						"audit_report_id": f"auditor_{int(time.time())}",
						"is_immune": False
					},
					color="red",
					emotion="alert"
				)

if __name__ == "__main__":
	import time
	logging.basicConfig(level=logging.INFO)
	auditor = SentinelAuditor(target_repos=[os.path.expanduser("~/Documents/IA/pure-mls"), os.path.expanduser("~/Documents/IA/sharing")])
	for repo in auditor.target_repos:
		res = auditor.audit_repo(repo)
		auditor.sync_to_thalamus(res)
		print(f"Audit of {repo}: {res.status} (Intensity: {res.intensity})")
