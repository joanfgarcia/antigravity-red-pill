"""
Service Health Contract — Dataclass + Manifest Loader.

Loads the services.yaml manifest and provides typed contracts
that the Sentinel plugin consumes to auto-configure monitoring.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

import platformdirs
import yaml

logger = logging.getLogger(__name__)

ServiceType = Literal["daemon-loop", "daemon-listener", "oneshot"]


@dataclass
class ServiceContract:
	"""Declares HOW a systemd service must be monitored."""

	name: str
	unit: str
	type: ServiceType
	loop_interval_s: Optional[int] = None
	watchdog_multiplier: int = 3
	health_url: Optional[str] = None
	max_runtime_s: Optional[int] = None
	legacy_aliases: List[str] = field(default_factory=list)

	@property
	def watchdog_sec(self) -> Optional[int]:
		"""Computed WatchdogSec for systemd. Only valid for daemon-loop."""
		if self.type == "daemon-loop" and self.loop_interval_s:
			return self.loop_interval_s * self.watchdog_multiplier
		return None

	@property
	def timeout_start_sec(self) -> Optional[int]:
		"""Computed TimeoutStartSec for systemd. Only valid for oneshot."""
		if self.type == "oneshot" and self.max_runtime_s:
			return self.max_runtime_s
		return None

	def validate(self) -> List[str]:
		"""Returns a list of validation errors. Empty list = valid."""
		errors: List[str] = []

		if self.type == "daemon-loop":
			if not self.loop_interval_s or self.loop_interval_s <= 0:
				errors.append(f"[{self.name}] daemon-loop requires loop_interval_s > 0")

		if self.type == "oneshot":
			if not self.max_runtime_s or self.max_runtime_s <= 0:
				errors.append(f"[{self.name}] oneshot requires max_runtime_s > 0")

		if self.type == "daemon-listener" and not self.health_url:
			errors.append(f"[{self.name}] daemon-listener should declare health_url")

		return errors


def _get_manifest_path() -> Path:
	"""Resolve manifest path: XDG config dir first, then fallback to examples/."""
	xdg_path = Path(platformdirs.user_config_dir("red-pill")) / "services.yaml"
	if xdg_path.exists():
		return xdg_path

	# Fallback: look in the repo examples/ directory
	repo_example = Path(__file__).parents[3] / "examples" / "services.yaml"
	if repo_example.exists():
		return repo_example

	return xdg_path  # Will fail gracefully on load


def load_manifest(path: Optional[Path] = None) -> Dict[str, ServiceContract]:
	"""
	Load and validate the services.yaml manifest.
	Returns a dict of service_name -> ServiceContract.
	"""
	manifest_path = path or _get_manifest_path()

	if not manifest_path.exists():
		logger.warning(f"Service manifest not found at {manifest_path}")
		return {}

	try:
		with open(manifest_path) as f:
			raw = yaml.safe_load(f)
	except Exception as e:
		logger.error(f"Failed to parse service manifest: {e}")
		return {}

	services_raw = raw.get("services", {})
	contracts: Dict[str, ServiceContract] = {}

	for name, cfg in services_raw.items():
		contract = ServiceContract(
			name=name,
			unit=cfg.get("unit", f"{name}.service"),
			type=cfg.get("type", "oneshot"),
			loop_interval_s=cfg.get("loop_interval_s"),
			watchdog_multiplier=cfg.get("watchdog_multiplier", 3),
			health_url=cfg.get("health_url"),
			max_runtime_s=cfg.get("max_runtime_s"),
			legacy_aliases=cfg.get("legacy_aliases", []),
		)

		errors = contract.validate()
		if errors:
			for err in errors:
				logger.warning(f"Service contract validation: {err}")

		contracts[name] = contract

	return contracts
