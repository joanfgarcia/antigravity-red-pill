"""
Red Pill Sentinel Auditor (v6.6.0-alpha)
The tactical 'Frontal Lobe' for sovereign infrastructure monitoring.
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AuditFinding:
	type: str  # 'formatting' | 'test' | 'security' | 'pain'
	severity: float  # 0.0 - 10.0
	message: str
	metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
	status: str  # 'green' | 'yellow' | 'red'
	findings: List[AuditFinding] = field(default_factory=list)
	intensity: float = 0.0


class SentinelAuditor:
	def __init__(self, target_repos: Optional[List[str]] = None, force: bool = False):
		self.target_repos = target_repos or []
		self.force = force
		self.logger = logging.getLogger("redpill.auditor")
		self.uv_path = os.path.expanduser("~/.local/bin/uv")
		from red_pill.memory import MemoryManager
		self.memory_mgr = MemoryManager()

	def audit_repo(self, repo_path: str) -> AuditReport:
		"""Run standard sovereign checks on a repository."""
		report = AuditReport(status="green")

		if not os.path.exists(repo_path):
			report.status = "red"
			report.findings.append(AuditFinding(type="infra", severity=10.0, message=f"Path not found: {repo_path}"))
			return report

		# 1. Formatting & Linting (Ruff)
		if not self.force and self.memory_mgr.has_signal("signal_ruff_failure"):
			self.logger.info("Skipping Ruff check (Fast-Fail: signal_ruff_failure exists)")
			report.status = "yellow"
			report.findings.append(AuditFinding(type="formatting", severity=5.0, message="Ruff check failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing formatting for {repo_path}")
			ruff = subprocess.run([self.uv_path, "run", "ruff", "check", "."], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			if ruff.returncode != 0:
				report.status = "yellow"
				errors = [line for line in ruff.stdout.splitlines() if ".py:" in line or "error" in line.lower()]
				detailed_msg = "\n".join(errors[:5]) if errors else (ruff.stdout[-300:] if ruff.stdout else "Ruff check failed")
				report.findings.append(
					AuditFinding(type="formatting", severity=5.0, message=f"Ruff check failed:\n{detailed_msg}", metadata={"stdout": ruff.stdout})
				)
			elif self.force:
				self.memory_mgr.evaporate_signals("signal_ruff_failure")
		# 2. Typing (Mypy)
		if not self.force and self.memory_mgr.has_signal("signal_mypy_failure"):
			self.logger.info("Skipping Mypy check (Fast-Fail: signal_mypy_failure exists)")
			report.status = "yellow"
			report.findings.append(AuditFinding(type="typing", severity=6.0, message="Mypy check failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing types for {repo_path}")
			mypy_target = "src/red_pill/" if os.path.exists(os.path.join(repo_path, "src/red_pill")) else "src/"
			mypy = subprocess.run([self.uv_path, "run", "mypy", mypy_target], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			if mypy.returncode != 0:
				report.status = "yellow"
				repo_name = os.path.basename(repo_path)

				# Parse Mypy output for explicit pain signals
				errors = []
				for line in mypy.stdout.splitlines():
					if "error:" in line:
						parts = line.split(":", 3)
						if len(parts) >= 3:
							file_path = parts[0].strip()
							line_num = parts[1].strip()
							msg = parts[3].strip() if len(parts) > 3 else parts[2].replace("error:", "").strip()
							errors.append(f"[{repo_name}] {file_path}:{line_num} -> {msg}")

				detailed_msg = "\n".join(errors) if errors else (mypy.stdout[-300:] if mypy.stdout else "Mypy type check failed")

				report.findings.append(
					AuditFinding(type="typing", severity=6.0, message=f"Mypy errors:\n{detailed_msg}", metadata={"stdout": mypy.stdout})
				)
			elif self.force:
				self.memory_mgr.evaporate_signals("signal_mypy_failure")
		# 3. Testing (Pytest)
		if not self.force and self.memory_mgr.has_signal("signal_pytest_failure"):
			self.logger.info("Skipping Pytest check (Fast-Fail: signal_pytest_failure exists)")
			report.status = "red"
			report.findings.append(AuditFinding(type="test", severity=8.0, message="Pytest suite failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing tests for {repo_path}")
			# Run standard tests (removed xdist to ensure universal compatibility)
			pytest = subprocess.run([self.uv_path, "run", "pytest"], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			if pytest.returncode != 0:
				report.status = "red"
				failed_tests = [line for line in pytest.stdout.splitlines() if line.startswith("FAILED ") or line.startswith("ERROR ")]
				detailed_msg = "\n".join(failed_tests[:5]) if failed_tests else (pytest.stdout[-300:] if pytest.stdout else "Pytest suite failed")
				if len(failed_tests) > 5:
					detailed_msg += f"\n... and {len(failed_tests) - 5} more failures."

				report.findings.append(
					AuditFinding(type="test", severity=8.0, message=f"Pytest suite failed:\n{detailed_msg}", metadata={"stdout": pytest.stdout})
				)
			elif self.force:
				self.memory_mgr.evaporate_signals("signal_pytest_failure")

		# Calculate global intensity based on findings
		report.intensity = sum(f.severity for f in report.findings)
		if any(f.severity >= 8.0 for f in report.findings):
			report.status = "red"
		elif report.findings:
			report.status = "yellow"

		return report

	def sync_to_thalamus(self, report: AuditReport):
		"""Inject audit findings into signal_memories."""
		self.logger.info(f"Sentinel Analysis complete. Status: {report.status}. Intensity: {report.intensity}")

		for finding in report.findings:
			if finding.severity >= 5.0 and "(Fast-Fail)" not in finding.message:
				# Deduce signal name and criticality
				signal_name = f"signal_{finding.type}_failure"
				criticality = "CRITICAL" if finding.severity >= 8.0 else "WARNING"

				self.logger.warning(f"Active Pain detected: {finding.message}")
				self.memory_mgr.inject_signal(
					name=signal_name,
					intensity=finding.severity,
					signal_type="pain",
					source="SentinelAuditor",
					criticality=criticality,
					originator="Sentinel"
				)


if __name__ == "__main__":
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument("--force", action="store_true", help="Force validation and heal existing signals")
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO)
	auditor = SentinelAuditor(target_repos=[os.path.expanduser("~/Documents/IA/pure-mls"), os.path.expanduser("~/Documents/IA/sharing")], force=args.force)
	for repo in auditor.target_repos:
		res = auditor.audit_repo(repo)
		auditor.sync_to_thalamus(res)
		print(f"Audit of {repo}: {res.status} (Intensity: {res.intensity})")
