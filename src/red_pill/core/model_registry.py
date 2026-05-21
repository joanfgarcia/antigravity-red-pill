import logging
import os
import shutil
from typing import Dict, Optional

import yaml

from red_pill.core.paths import get_bunker_root, get_model_profiles_path
from red_pill.core.vram_probe import VramProbe

logger = logging.getLogger(__name__)


class ModelRegistry:
	_profiles_cache: Optional[Dict[str, dict]] = None

	@classmethod
	def get_profile(cls, profile_name: str) -> dict:
		if cls._profiles_cache is None:
			cls._load_profiles()
		if cls._profiles_cache is not None:
			return cls._profiles_cache.get(profile_name, {})
		return {}

	@classmethod
	def get_profile_by_capability(cls, required_capability: str) -> tuple[str, dict]:
		if cls._profiles_cache is None:
			cls._load_profiles()
		if cls._profiles_cache is not None:
			for name, profile in cls._profiles_cache.items():
				caps = profile.get("capabilities", [])
				if required_capability in caps:
					return name, profile
			# Fallback to the first available profile if none match exactly
			if cls._profiles_cache:
				first_name = list(cls._profiles_cache.keys())[0]
				return first_name, cls._profiles_cache[first_name]
		return "", {}

	@classmethod
	def _load_profiles(cls):
		config_path = str(get_model_profiles_path())
		# Fallback seed resolved dynamically via bunker root
		seed_path = os.path.join(get_bunker_root(), "examples", "model_profiles.yaml.example")

		# Auto-seed if missing
		if not os.path.exists(config_path):
			try:
				os.makedirs(os.path.dirname(config_path), exist_ok=True)
				if os.path.exists(seed_path):
					shutil.copy2(seed_path, config_path)
					logger.info(f"Seeded model profiles to {config_path}")
			except Exception as e:
				logger.error(f"Failed to seed profiles: {e}")

		cls._profiles_cache = {}
		if os.path.exists(config_path):
			try:
				with open(config_path, "r") as f:
					data = yaml.safe_load(f)
					if data and "profiles" in data:
						cls._profiles_cache.update(data["profiles"])
			except Exception as e:
				logger.error(f"Failed to load model profiles from {config_path}: {e}")

	@classmethod
	def get_resolved_hardware_affinity(cls, profile_name: str) -> dict:
		"""Resolves hardware affinity based on free VRAM available right now.

		Uses VramProbe.get_free_mb() to detect how much VRAM is currently free
		on the host GPU (no cache — always a fresh query). The result determines
		which vram_tiers entry is selected.

		Each tier's 'min_free_gb' field represents the minimum free VRAM required
		to use that tier. Tiers are sorted ascending; the first tier whose
		min_free_gb is satisfied by the currently free VRAM is selected.
		If free VRAM exceeds all tiers, the highest tier is used.

		On CPU-only systems (VramProbe returns 0 MB), the lowest (most
		conservative) tier is always selected.
		"""
		profile = cls.get_profile(profile_name)
		hardware: dict = profile.get("hardware_affinity", {})

		if "vram_tiers" not in hardware:
			return hardware

		free_vram_mb = VramProbe.get_free_mb()
		free_vram_gb = free_vram_mb / 1024.0

		resolved = {k: v for k, v in hardware.items() if k != "vram_tiers"}

		# Sort tiers by min_free_gb ascending; select the first tier that fits
		tiers = sorted(hardware["vram_tiers"], key=lambda x: x.get("min_free_gb", 0))
		matched_tier = None
		for tier in tiers:
			if free_vram_gb <= tier.get("min_free_gb", 0):
				matched_tier = tier
				break
		else:
			# Free VRAM exceeds all defined tiers → use the highest
			if tiers:
				matched_tier = tiers[-1]

		if matched_tier:
			logger.info(f"[ModelRegistry] Free VRAM {free_vram_gb:.2f} GB → tier: {matched_tier}")
			for k, v in matched_tier.items():
				if k != "min_free_gb":
					resolved[k] = v

		return resolved
