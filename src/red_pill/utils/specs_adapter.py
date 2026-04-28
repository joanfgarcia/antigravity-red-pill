from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore


class SpecsAdapter:
	"""
	Elastic Adapter for specs.md framework integration.
	Detects and parses specs.md artifacts (Simple, FIRE, AI-DLC)
	without hard-dependency on framework internal code.
	"""

	FLOW_MAP = {"fire": [".specsmd/fire/"], "simple": ["specs/"], "aidlc": ["aidlc-docs/"]}

	def __init__(self, workspace_root: str):
		self.root = Path(workspace_root)

	def detect_flow(self) -> Optional[str]:
		"""Auto-detect which specs.md flow is active in the workspace."""
		for flow, paths in self.FLOW_MAP.items():
			for path in paths:
				if (self.root / path).exists():
					return flow
		return None

	def get_fire_intents(self) -> List[Dict[str, Any]]:
		"""Retrieve intents from a FIRE flow."""
		# Check both legacy and new specsmd locations
		checkpoints = [self.root / ".specsmd/fire/resources/state.yaml", self.root / ".specsmd/state.yaml"]
		checkpoint = None
		for p in checkpoints:
			if p.exists():
				checkpoint = p
				break

		if checkpoint is None:
			return []

		try:
			data = yaml.safe_load(checkpoint.read_text())
			intents = data.get("intents", [])
			return list(intents) if isinstance(intents, list) else []
		except Exception:
			return []

	def get_simple_tasks(self) -> str:
		"""Retrieve high-level tasks from Simple Flow specs."""
		tasks_path = self.root / "specs/tasks.md"
		if not tasks_path.exists():
			return ""
		return tasks_path.read_text()

	def is_specs_aware(self) -> bool:
		"""Check if the project has any specs.md footprint."""
		return self.detect_flow() is not None

	def get_specs_hash(self) -> str:
		"""Calculate a deterministic hash of current specs.md artifacts."""
		import hashlib

		flow = self.detect_flow()
		if not flow:
			return ""
		hasher = hashlib.sha256()
		# Add flow name to distinguish identical contents in different flows
		hasher.update(flow.encode())
		# Hashing implementation (v5.6.2)
		if flow == "simple":
			specs_dir = Path(self.root) / "specs"
			if specs_dir.exists():
				for p in sorted(specs_dir.glob("*.md")):
					hasher.update(p.read_bytes())
		elif flow == "fire":
			# Hash the state file or memory-bank if they exist
			checkpoints = [
				self.root / ".specs-fire/state.yaml",
				self.root / ".specsmd/fire/memory-bank.yaml",
				self.root / ".specsmd/fire/resources/state.yaml",
				self.root / ".specsmd/state.yaml",
			]
			for p in checkpoints:
				if p.exists():
					hasher.update(p.read_bytes())
					break
		return str(hasher.hexdigest())
