"""
Red Pill Sentinel Auditor (v6.6.0-alpha)
The tactical 'Frontal Lobe' for sovereign infrastructure monitoring.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
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

		# Auditor Cache System
		from red_pill.core.paths import get_data_dir

		self.cache_file = get_data_dir() / "auditor_cache.json"
		self.cache_file.parent.mkdir(parents=True, exist_ok=True)

		from red_pill.memory import MemoryManager

		self.memory_mgr = MemoryManager()

	def _get_project_mtime(self, repo_path: str) -> float:
		"""Calculates the maximum modification time (mtime) of all python source files."""
		repo_dir = Path(repo_path)
		if not repo_dir.exists():
			return 0.0

		max_mtime = 0.0
		# Check all python files
		for p in repo_dir.rglob("*.py"):
			if p.is_file():
				try:
					max_mtime = max(max_mtime, p.stat().st_mtime)
				except FileNotFoundError:
					pass

		# Check pyproject.toml as well
		for p in repo_dir.rglob("pyproject.toml"):
			if p.is_file():
				try:
					max_mtime = max(max_mtime, p.stat().st_mtime)
				except FileNotFoundError:
					pass

		return max_mtime

	def _get_cached_mtime(self, repo_path: str) -> float:
		"""Retrieves the cached mtime for a given repository."""
		if not self.cache_file.exists():
			return 0.0
		try:
			with open(self.cache_file, "r") as f:
				cache = json.load(f)
			return float(cache.get(repo_path, 0.0))
		except Exception:
			return 0.0

	def _update_cached_mtime(self, repo_path: str, new_mtime: float):
		"""Updates the cached mtime for a given repository."""
		cache = {}
		if self.cache_file.exists():
			try:
				with open(self.cache_file, "r") as f:
					cache = json.load(f)
			except Exception:
				pass

		cache[repo_path] = new_mtime
		try:
			with open(self.cache_file, "w") as f:
				json.dump(cache, f, indent=4)
		except Exception as e:
			self.logger.warning(f"Failed to update auditor cache: {e}")

	def audit_repo(self, repo_path: str) -> AuditReport:
		"""Run standard sovereign checks on a repository."""
		report = AuditReport(status="green")

		if not os.path.exists(repo_path):
			report.status = "red"
			report.findings.append(AuditFinding(type="infra", severity=10.0, message=f"Path not found: {repo_path}"))
			return report

		# --- Differential Audit Cache Check ---
		current_mtime = self._get_project_mtime(repo_path)
		cached_mtime = self._get_cached_mtime(repo_path)

		if not self.force and current_mtime <= cached_mtime:
			self.logger.info(f"Skipping audit for {repo_path} (No changes detected since last audit)")
			return report  # Returns default green status with no findings
		# --------------------------------------

		# 1. Formatting & Linting (Ruff)
		if not self.force and self.memory_mgr.has_signal("signal_formatting_failure"):
			self.logger.info("Skipping Ruff check (Fast-Fail: signal_formatting_failure exists)")
			report.status = "yellow"
			report.findings.append(AuditFinding(type="formatting", severity=5.0, message="Ruff check failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing formatting for {repo_path}")
			ruff = subprocess.run(
				[self.uv_path, "run", "ruff", "check", "."], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
			)
			if ruff.returncode != 0:
				report.status = "yellow"
				errors = [line for line in ruff.stdout.splitlines() if ".py:" in line or "error" in line.lower()]
				detailed_msg = "\n".join(errors[:5]) if errors else (ruff.stdout[-300:] if ruff.stdout else "Ruff check failed")
				report.findings.append(
					AuditFinding(type="formatting", severity=5.0, message=f"Ruff check failed:\n{detailed_msg}", metadata={"stdout": ruff.stdout})
				)
			else:
				self.memory_mgr.evaporate_signals("signal_formatting_failure")
		# 2. Typing (Mypy)
		if not self.force and self.memory_mgr.has_signal("signal_typing_failure"):
			self.logger.info("Skipping Mypy check (Fast-Fail: signal_typing_failure exists)")
			report.status = "yellow"
			report.findings.append(AuditFinding(type="typing", severity=5.0, message="Mypy check failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing types for {repo_path}")
			mypy_target = "src/red_pill/" if os.path.exists(os.path.join(repo_path, "src/red_pill")) else "src/"
			mypy = subprocess.run(
				[self.uv_path, "run", "mypy", mypy_target], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
			)
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
					AuditFinding(type="typing", severity=5.0, message=f"Mypy errors:\n{detailed_msg}", metadata={"stdout": mypy.stdout})
				)
			else:
				self.memory_mgr.evaporate_signals("signal_typing_failure")
		# 3. Testing (Pytest)
		if not self.force and self.memory_mgr.has_signal("signal_test_failure"):
			self.logger.info("Skipping Pytest check (Fast-Fail: signal_test_failure exists)")
			report.status = "yellow"
			report.findings.append(AuditFinding(type="test", severity=5.0, message="Pytest suite failed (Fast-Fail)"))
		else:
			self.logger.info(f"Auditing tests for {repo_path}")
			# Run standard tests (removed xdist to ensure universal compatibility)
			pytest = subprocess.run([self.uv_path, "run", "pytest"], cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			if pytest.returncode != 0:
				report.status = "yellow"
				failed_tests = [line for line in pytest.stdout.splitlines() if line.startswith("FAILED ") or line.startswith("ERROR ")]
				detailed_msg = "\n".join(failed_tests[:5]) if failed_tests else (pytest.stdout[-300:] if pytest.stdout else "Pytest suite failed")
				if len(failed_tests) > 5:
					detailed_msg += f"\n... and {len(failed_tests) - 5} more failures."

				report.findings.append(
					AuditFinding(type="test", severity=5.0, message=f"Pytest suite failed:\n{detailed_msg}", metadata={"stdout": pytest.stdout})
				)
			else:
				self.memory_mgr.evaporate_signals("signal_test_failure")

		# Calculate global intensity based on findings
		report.intensity = sum(f.severity for f in report.findings)
		if any(f.severity >= 8.0 for f in report.findings):
			report.status = "red"
		elif report.findings:
			report.status = "yellow"

		# Update Cache if audit ran
		self._update_cached_mtime(repo_path, current_mtime)

		return report

	def _read_log_tail(self, filepath: Path, max_bytes: int = 10240) -> List[str]:
		"""Reads the tail of a file safely up to max_bytes, returning lines."""
		if not filepath.exists() or not filepath.is_file():
			return []
		try:
			file_size = filepath.stat().st_size
			with open(filepath, "rb") as f:
				if file_size > max_bytes:
					f.seek(-max_bytes, os.SEEK_END)
					chunk = f.read(max_bytes)
				else:
					chunk = f.read()
				lines = chunk.decode("utf-8", errors="ignore").splitlines()
				if file_size > max_bytes and lines:
					lines.pop(0)
				return lines
		except Exception as e:
			self.logger.warning(f"Failed to read tail of {filepath}: {e}")
			return []

	def audit_runtime(self) -> AuditReport:
		"""Run dynamic runtime checks on Daemons and Logs."""
		report = AuditReport(status="green")
		self.logger.info("Auditing System Daemons and Runtime Logs...")

		# 1. Find all redpill units
		units_res = subprocess.run(
			["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
		)
		redpill_units = [line.split()[0] for line in units_res.stdout.splitlines() if line.startswith("redpill-")]

		# 2. Check failed systemd units
		failed_res = subprocess.run(
			["systemctl", "--user", "list-units", "--state=failed", "--plain", "--no-legend"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
		)
		failed_daemons = [line.split()[0] for line in failed_res.stdout.splitlines() if line.startswith("redpill-")]

		if failed_daemons:
			report.status = "red"
			report.findings.append(
				AuditFinding(
					type="daemon",
					severity=9.0,
					message="Failed Red Pill daemons detected:\n" + "\n".join(failed_daemons),
					metadata={"failed_units": failed_daemons},
				)
			)
		else:
			self.memory_mgr.evaporate_signals("signal_daemon_failure")

		# 3. Scan journalctl for errors since last audit using a cursor file
		all_errors = []
		if redpill_units:
			from red_pill.core.paths import get_data_dir

			cursor_file = get_data_dir() / "auditor_journal_cursor"
			if not cursor_file.exists():
				# Initialize cursor at the current end of journal to avoid parsing history
				subprocess.run(["journalctl", "--user", "-n", "0", f"--cursor-file={cursor_file}"])

			cmd = ["journalctl", "--user", f"--cursor-file={cursor_file}", "--no-pager", "-p", "4"]
			for u in redpill_units:
				cmd.extend(["-u", u])

			jour_res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
			if jour_res.returncode == 0:
				for line in jour_res.stdout.splitlines():
					# Case-insensitive check for error signatures
					line_lower = line.lower()
					if "error" in line_lower or "exception" in line_lower or "traceback" in line_lower or "fatal" in line_lower:
						if "llama_model_loader" in line_lower:
							continue
						# Prevent self-referential feedback loops from the auditor's own logging
						if "active pain detected" in line_lower or "recent daemon errors in journal" in line_lower:
							continue
						# Filter ASGI/uvicorn framework internals (not real application errors)
						if "exception in asgi application" in line_lower:
							continue
						if "starlette/" in line_lower or "uvicorn/" in line_lower:
							continue
						all_errors.append(line)

		# 4. Scan external service error logs (stdout/stderr redirected to files)
		external_logs = [
			Path.home() / ".local/share/red-pill/daemon/error.log",
			Path.home() / ".agent/bunker_daemon_error.log",
		]
		for log_path in external_logs:
			if log_path.exists():
				lines = self._read_log_tail(log_path)
				for line in lines:
					line_lower = line.lower()
					if "error" in line_lower or "exception" in line_lower or "traceback" in line_lower or "fatal" in line_lower:
						if "llama_model_loader" in line_lower:
							continue
						if "active pain detected" in line_lower or "recent daemon errors in journal" in line_lower:
							continue
						# Filter benign ASGI/uvicorn framework noise (model load/unload cycles)
						if "exception in asgi application" in line_lower:
							continue
						if "starlette/" in line_lower or "uvicorn/" in line_lower:
							continue
						# Filter GNOME desktop noise (gnome-keyring, gnome-software, gnome-shell)
						if "gnome-keyring" in line_lower or "gnome-software" in line_lower or "gnome-shell" in line_lower:
							continue
						all_errors.append(f"[{log_path.name}] {line}")

		if all_errors:
			report.status = "yellow" if report.status == "green" else report.status
			detailed_msg = "\n".join(all_errors[:10])
			if len(all_errors) > 10:
				detailed_msg += f"\n... and {len(all_errors) - 10} more errors."
			report.findings.append(
				AuditFinding(
					type="journal",
					severity=6.0,
					message=f"Recent daemon errors in journal:\n{detailed_msg}",
					metadata={"error_count": len(all_errors)},
				)
			)
		else:
			self.memory_mgr.evaporate_signals("signal_journal_failure")

		# Calculate global intensity based on findings
		report.intensity = sum(f.severity for f in report.findings)
		if any(f.severity >= 8.0 for f in report.findings):
			report.status = "red"
		elif report.findings:
			report.status = "yellow"

		return report

	def audit_vitals(self) -> AuditReport:
		"""Run dynamic runtime checks on System Vitals (Memory, VRAM, Net)."""
		report = AuditReport(status="green")
		self.logger.info("Auditing System Vitals...")

		# -- DYNAMIC PLUGIN DISCOVERY --
		import importlib
		import inspect
		import pkgutil

		import red_pill.config as cfg
		import red_pill.metabolism.sentinel_plugins as plugins_pkg
		from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

		config = cfg.get_config()

		try:
			for _, name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
				module = importlib.import_module(f"red_pill.metabolism.sentinel_plugins.{name}")
				for _, obj in inspect.getmembers(module, inspect.isclass):
					if issubclass(obj, SentinelPlugin) and obj is not SentinelPlugin and not inspect.isabstract(obj):
						plugin = obj()
						try:
							if plugin.is_enabled(config):
								self.logger.info(f"Executing health check plugin: {plugin.name}")
								plugin_findings = plugin.audit(config)
								if plugin_findings:
									for finding in plugin_findings:
										self.logger.warning(f"Sentinel Auditor: Detected issue '{finding.type}': {finding.message}")
										healed = False
										try:
											healed = plugin.heal(config, finding)
										except Exception as heal_err:
											self.logger.error(f"Plugin {plugin.name} failed during heal: {heal_err}")

										if healed:
											self.logger.info(
												f"Sentinel Auditor: Successfully healed '{finding.type}' for {finding.metadata.get('service', 'unknown')}"
											)
										else:
											self.logger.warning(f"Sentinel Auditor: Auto-heal failed/not supported for '{finding.type}'")
											report.findings.append(finding)
						except Exception as e:
							self.logger.error(f"Plugin {plugin.name} failed during audit: {e}")
							report.status = "red"
							report.findings.append(AuditFinding(type="blindness", severity=10.0, message=f"Plugin {plugin.name} CRASHED: {e}"))
		except Exception as e:
			self.logger.error(f"Failed to load sentinel plugins: {e}")

		# 3. VRAM Exhaustion
		try:
			vram_res = subprocess.run(
				["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], stdout=subprocess.PIPE, text=True
			)
		except FileNotFoundError:
			# No NVIDIA host — skip VRAM check, never drop the whole vitals report.
			vram_res = None
		if vram_res is not None and vram_res.returncode == 0 and vram_res.stdout.strip():
			try:
				used, total = map(int, vram_res.stdout.strip().split(","))
				if total > 0 and (used / total) > 0.95:
					report.status = "yellow" if report.status == "green" else report.status
					report.findings.append(AuditFinding(type="exhaustion", severity=8.0, message=f"VRAM Exhaustion Risk: {used}/{total} MB"))
			except Exception:
				pass

		# 4. Sensory Blindness (Network/LLM)
		import urllib.error
		import urllib.request

		try:
			urllib.request.urlopen("https://api.openai.com/v1/models", timeout=3)
		except Exception as e:
			if hasattr(e, "code") and e.code == 401:
				pass
			else:
				report.status = "yellow" if report.status == "green" else report.status
				report.findings.append(
					AuditFinding(type="blindness", severity=7.0, message=f"Sensory Blindness: Cannot reach external LLM endpoints ({e})")
				)

		# 5. OOM Killer in dmesg
		dmesg_res = subprocess.run(["dmesg", "-T"], stdout=subprocess.PIPE, text=True)
		if dmesg_res.returncode == 0:
			oom_lines = [line for line in dmesg_res.stdout.splitlines()[-500:] if "Out of memory: Killed process" in line and "redpill" in line]
			if oom_lines:
				report.status = "red"
				report.findings.append(
					AuditFinding(
						type="exhaustion", severity=10.0, message="OOM Killer executed against a redpill process:\n" + "\n".join(oom_lines[-5:])
					)
				)

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
					originator="Sentinel",
				)
				# Drop a task report in MinionInbox for repository checks (formatting, typing, test)
				if finding.type in ("formatting", "typing", "test"):
					try:
						from red_pill.core.inbox import MinionInbox

						MinionInbox().drop_report(
							event_id=signal_name,
							source="SentinelAuditor",
							status="pain",
							content=finding.message,
							originator="Sentinel",
						)
						self.logger.info(f"Dropped auto-heal task in MinionInbox for '{signal_name}'")
					except Exception as inbox_ex:
						self.logger.error(f"Failed to drop task in MinionInbox: {inbox_ex}")


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument("--force", action="store_true", help="Force validation and heal existing signals")
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO)
	from red_pill.core.paths import get_bunker_root

	auditor = SentinelAuditor(target_repos=[str(get_bunker_root().parent / "pure-mls"), str(get_bunker_root())], force=args.force)
	for repo in auditor.target_repos:
		res = auditor.audit_repo(repo)
		auditor.sync_to_thalamus(res)
		print(f"Audit of {repo}: {res.status} (Intensity: {res.intensity})")
