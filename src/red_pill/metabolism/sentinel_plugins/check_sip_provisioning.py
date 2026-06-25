"""
Sentinel Plugin: SIP Provisioning — full infrastructure validation.

Unlike check_sip.py (which validates runtime health when the service IS running),
this plugin validates the PROVISIONING CHAIN:

1. start.sh exists in $XDG_RUNTIME_DIR/red-pill/ (volatile — lost on reboot)
2. run_dual_bind.py exists in same dir (volatile)
3. .venv/ exists with llama-cpp-python installed (volatile)
4. systemd service file exists at ~/.config/systemd/user/redpill-llm.service (persistent)
5. Model GGUF file exists (resolved from model_profiles.yaml)
6. UDS socket path consistency (config.py vs run_dual_bind.py)
7. setup_background_model.sh exists in APP_ROOT/scripts/ (the provisioner itself)

heal_specific: re-runs setup_background_model.sh to reconstruct volatile artifacts.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.service_base import ServiceSentinelPlugin

logger = logging.getLogger(__name__)


class SipProvisioningCheck(ServiceSentinelPlugin):
	@property
	def name(self) -> str:
		return "SIP Provisioning (Volatile Artifacts)"

	@property
	def service_unit(self) -> str:
		return "redpill-llm.service"

	@property
	def config_key(self) -> Optional[str]:
		return "SIP_ENABLED"

	def audit_health(self, cfg: Any) -> List[AuditFinding]:
		"""Validate the full provisioning chain even when the service appears active.

		This catches the case where the service unit exists but is stale
		(e.g. after reboot the ExecStart path points to a vanished start.sh).
		"""
		return self._audit_provisioning(cfg)

	def audit(self, cfg: Any) -> List[AuditFinding]:
		"""Override base audit to ALWAYS run provisioning checks.

		The base class skips audit_health() when the service is down (it only
		emits a service_down finding). But for provisioning, we need to know
		WHY it's down — missing artifacts are the root cause, not the symptom.
		"""
		# Run base reconciliation first (service_down / service_unwanted)
		base_findings = super().audit(cfg)

		# If the service should be active (desired), always run provisioning audit
		if self._is_desired_active(cfg):
			provisioning_findings = self._audit_provisioning(cfg)
			# Merge, avoiding duplicates
			base_types = {f.type for f in base_findings}
			for pf in provisioning_findings:
				if pf.type not in base_types:
					base_findings.append(pf)

		return base_findings

	# ── Provisioning checks ──────────────────────────────────

	def _audit_provisioning(self, cfg: Any) -> List[AuditFinding]:
		"""Check each artifact in the SIP provisioning chain."""
		findings: List[AuditFinding] = []

		from red_pill.core.paths import get_daemon_dir, get_daemon_persistent_dir

		runtime_dir = get_daemon_dir()
		persistent_dir = get_daemon_persistent_dir()
		app_root = getattr(cfg, "APP_ROOT", os.getenv("APP_ROOT", ""))

		# 1. start.sh — persistent (survives reboot)
		start_sh = persistent_dir / "start.sh"
		if not start_sh.exists():
			findings.append(
				AuditFinding(
					type="sip_missing_start_sh",
					severity=8.0,
					message=(f"{self.name}: start.sh not found at {start_sh}. Run setup_background_model.sh to create it."),
					metadata={"service": self.service_unit, "path": str(start_sh), "volatile": False},
				)
			)

		# 2. run_dual_bind.py — persistent
		dual_bind = persistent_dir / "run_dual_bind.py"
		if not dual_bind.exists():
			findings.append(
				AuditFinding(
					type="sip_missing_dual_bind",
					severity=7.0,
					message=(
						f"{self.name}: run_dual_bind.py not found at {dual_bind}. The dual-bind TCP+UDS server script is required for the SIP daemon."
					),
					metadata={"service": self.service_unit, "path": str(dual_bind), "volatile": False},
				)
			)

		# 3. .venv/ with llama-cpp-python — persistent
		venv_dir = persistent_dir / ".venv"
		if not venv_dir.exists():
			findings.append(
				AuditFinding(
					type="sip_missing_venv",
					severity=8.0,
					message=(f"{self.name}: Isolated venv not found at {venv_dir}. The llama-cpp-python[server] environment is required."),
					metadata={"service": self.service_unit, "path": str(venv_dir), "volatile": False},
				)
			)
		else:
			# Venv exists — verify llama-cpp-python is installed
			if not self._is_llama_cpp_installed(venv_dir):
				findings.append(
					AuditFinding(
						type="sip_missing_llama_cpp",
						severity=7.0,
						message=(f"{self.name}: venv exists at {venv_dir} but llama-cpp-python is not installed."),
						metadata={"service": self.service_unit, "path": str(venv_dir)},
					)
				)

		# 4. systemd service file — persistent (survives reboot)
		service_path = Path.home() / ".config" / "systemd" / "user" / "redpill-llm.service"
		if not service_path.exists():
			findings.append(
				AuditFinding(
					type="sip_missing_service_file",
					severity=6.0,
					message=(f"{self.name}: systemd user service file not found at {service_path}. Run setup_background_model.sh to create it."),
					metadata={"service": self.service_unit, "path": str(service_path), "volatile": False},
				)
			)

		# 5. Model GGUF file — resolved from model_profiles.yaml
		model_finding = self._check_model_file()
		if model_finding:
			findings.append(model_finding)

		# 6. UDS socket path consistency (socket goes to runtime dir)
		uds_finding = self._check_uds_consistency(cfg, runtime_dir)
		if uds_finding:
			findings.append(uds_finding)

		# 7. setup_background_model.sh — the provisioner itself
		if app_root:
			setup_script = Path(app_root) / "scripts" / "setup_background_model.sh"
			if not setup_script.exists():
				findings.append(
					AuditFinding(
						type="sip_missing_setup_script",
						severity=9.0,
						message=(
							f"{self.name}: setup_background_model.sh not found at {setup_script}. "
							"Cannot re-provision SIP infrastructure without the setup script."
						),
						metadata={"service": self.service_unit, "path": str(setup_script)},
					)
				)

		return findings

	def _is_llama_cpp_installed(self, venv_dir: Path) -> bool:
		"""Check if llama-cpp-python is installed in the given venv.

		Uses site-packages directory scan instead of pip show, since
		uv-created venvs don't ship pip by default.
		"""
		try:
			# Find site-packages in the venv
			lib_dir = venv_dir / "lib"
			if not lib_dir.exists():
				return False
			for pydir in lib_dir.iterdir():
				if pydir.name.startswith("python"):
					site_packages = pydir / "site-packages"
					if site_packages.exists():
						# Check for llama_cpp package directory
						for item in site_packages.iterdir():
							if item.name.startswith("llama_cpp"):
								return True
			return False
		except Exception:
			return False

	def _check_model_file(self) -> Optional[AuditFinding]:
		"""Resolve model path from model_profiles.yaml and verify it exists."""
		try:
			from red_pill.core.paths import get_model_profiles_path

			profiles_path = get_model_profiles_path()
			if not profiles_path.exists():
				return AuditFinding(
					type="sip_missing_model_profiles",
					severity=5.0,
					message=f"{self.name}: model_profiles.yaml not found at {profiles_path}.",
					metadata={"service": self.service_unit, "path": str(profiles_path)},
				)

			import yaml

			with open(profiles_path, "r") as f:
				data = yaml.safe_load(f) or {}

			profiles = data.get("profiles", {})
			# Check the default profile (samantha) or the one set in env
			profile_name = os.getenv("MINION_PROFILE", "samantha")
			profile = profiles.get(profile_name)
			if not profile:
				return AuditFinding(
					type="sip_missing_model_profile",
					severity=5.0,
					message=f"{self.name}: Profile '{profile_name}' not found in model_profiles.yaml.",
					metadata={"service": self.service_unit, "profile": profile_name},
				)

			model_path_raw = profile.get("model_path", "")
			if not model_path_raw:
				return None

			# Resolve relative paths through resolve_model_path
			model_path = Path(model_path_raw)
			if not model_path.is_absolute():
				from red_pill.core.paths import resolve_model_path

				model_path = resolve_model_path(os.path.basename(model_path_raw))

			if not model_path.exists():
				return AuditFinding(
					type="sip_missing_model_file",
					severity=6.0,
					message=(f"{self.name}: Model GGUF file not found at {model_path} (profile: {profile_name}). The SIP daemon will fail to load."),
					metadata={
						"service": self.service_unit,
						"path": str(model_path),
						"profile": profile_name,
						"hf_repo": profile.get("hf_model_repo_id", "unknown"),
					},
				)
		except Exception as e:
			logger.warning(f"[{self.name}] Failed to validate model file: {e}")
		return None

	def _check_uds_consistency(self, cfg: Any, daemon_dir: Path) -> Optional[AuditFinding]:
		"""Verify that config.py's SIP_SOCKET_PATH matches what run_dual_bind.py creates."""
		config_socket = getattr(cfg, "SIP_SOCKET_PATH", "")
		expected_socket = str(daemon_dir / "red_pill.sock")

		if config_socket and os.path.normpath(config_socket) != os.path.normpath(expected_socket):
			return AuditFinding(
				type="sip_uds_mismatch",
				severity=7.0,
				message=(
					f"{self.name}: UDS socket path mismatch! "
					f"config.py SIP_SOCKET_PATH='{config_socket}' but "
					f"run_dual_bind.py creates socket at '{expected_socket}'. "
					"Internal modules connecting via UDS will fail silently."
				),
				metadata={
					"service": self.service_unit,
					"config_path": config_socket,
					"expected_path": expected_socket,
				},
			)
		return None

	# ── Healing ──────────────────────────────────────────────

	def heal_specific(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Re-provision the SIP infrastructure by running setup_background_model.sh.

		Wraps the heavy subprocess with OOM Shield (systemd-run --user --scope
		-p MemoryMax=10G) to prevent system OOM panics.
		"""
		# UDS mismatch is a code-level fix, not a runtime heal
		if finding.type == "sip_uds_mismatch":
			logger.warning(
				f"[{self.name}] UDS path mismatch requires a code fix in config.py. "
				"Cannot auto-heal. Apply the fix: SIP_SOCKET_PATH should use get_daemon_dir()."
			)
			return False

		# Missing setup script — nothing we can do
		if finding.type == "sip_missing_setup_script":
			logger.error(f"[{self.name}] Cannot heal: setup script itself is missing.")
			return False

		# For all volatile artifact issues, re-run the setup script
		app_root = getattr(cfg, "APP_ROOT", os.getenv("APP_ROOT", ""))
		setup_script = os.path.join(app_root, "scripts", "setup_background_model.sh") if app_root else ""

		if not setup_script or not os.path.exists(setup_script):
			logger.error(f"[{self.name}] Cannot locate setup_background_model.sh at {setup_script}")
			return False

		try:
			logger.info(f"[{self.name}] Re-provisioning SIP infrastructure via {setup_script}")

			# OOM Shield Protocol: wrap with systemd-run to contain memory usage
			result = subprocess.run(
				[
					"systemd-run",
					"--user",
					"--scope",
					"-p",
					"MemoryMax=10G",
					"/bin/bash",
					setup_script,
				],
				capture_output=True,
				text=True,
				timeout=300,
				env={**os.environ, "APP_ROOT": app_root},
			)

			if result.returncode != 0:
				logger.error(f"[{self.name}] setup_background_model.sh failed (rc={result.returncode}): {result.stderr[-500:]}")
				return False

			logger.info(f"[{self.name}] SIP infrastructure re-provisioned successfully.")

			# Reload and restart the systemd service (setup script does this,
			# but ensure it's done in case the script was interrupted)
			subprocess.run(
				["systemctl", "--user", "daemon-reload"],
				check=False,
				timeout=15,
			)
			self._restart_service()

			# Evaporate stale pain signals
			try:
				from red_pill.memory import MemoryManager

				mm = MemoryManager()
				mm.evaporate_signals("local_llm_offline")
				mm.evaporate_signals("signal_sip_missing_start_sh_failure")
				mm.evaporate_signals("signal_sip_missing_venv_failure")
				mm.evaporate_signals("signal_sip_missing_dual_bind_failure")
				mm.evaporate_signals("signal_service_down_failure")
			except Exception as evap_err:
				logger.warning(f"[{self.name}] Failed to evaporate stale signals: {evap_err}")

			return True

		except subprocess.TimeoutExpired:
			logger.error(f"[{self.name}] setup_background_model.sh timed out (300s limit)")
			return False
		except Exception as e:
			logger.error(f"[{self.name}] Failed to re-provision SIP infrastructure: {e}")
			return False
