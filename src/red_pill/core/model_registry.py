import logging
import os
import shutil
from typing import Dict, Optional

import yaml

from red_pill.core.paths import get_bunker_root, get_model_profiles_path

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
		"""Resolves hardware affinity dynamically based on available VRAM tiers."""
		profile = cls.get_profile(profile_name)
		hardware = profile.get("hardware_affinity", {})

		# If vram_tiers is defined, resolve dynamically based on VRAM
		if "vram_tiers" in hardware:
			try:
				from red_pill.telemetry import sentinel
				stats = sentinel.get_stats()
				gpus = stats.get("gpu", [])
				total_vram_mb = 0
				if gpus:
					# Parse "memory": "used/total MB" (e.g. "120/8151 MB")
					mem_str = gpus[0].get("memory", "0/0 MB")
					parts = mem_str.split("/")
					if len(parts) > 1:
						total_vram_mb = int(parts[1].split()[0])
				total_vram_gb = total_vram_mb / 1024.0
			except Exception as e:
				logger.warning(f"Failed to detect GPU VRAM: {e}. Defaulting to lowest tier.")
				total_vram_gb = 0.0

			resolved = {}
			for k, v in hardware.items():
				if k != "vram_tiers":
					resolved[k] = v

			# Find matching tier
			tiers = sorted(hardware["vram_tiers"], key=lambda x: x.get("limit_gb", 0))
			matched_tier = None
			for tier in tiers:
				if total_vram_gb <= tier.get("limit_gb", 0):
					matched_tier = tier
					break
			else:
				if tiers:
					matched_tier = tiers[-1]

			if matched_tier:
				logger.info(f"Resolved hardware affinity for VRAM {total_vram_gb:.2f} GB: {matched_tier}")
				for k, v in matched_tier.items():
					if k != "limit_gb":
						resolved[k] = v
			return resolved

		return hardware
