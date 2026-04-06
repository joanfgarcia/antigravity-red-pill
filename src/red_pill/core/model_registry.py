import logging
import os
import shutil

import yaml

logger = logging.getLogger(__name__)

class ModelRegistry:
	_profiles_cache = None

	@classmethod
	def get_profile(cls, profile_name: str) -> dict:
		if cls._profiles_cache is None:
			cls._load_profiles()
		return cls._profiles_cache.get(profile_name, {})

	@classmethod
	def get_profile_by_capability(cls, required_capability: str) -> tuple[str, dict]:
		if cls._profiles_cache is None:
			cls._load_profiles()
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
		config_path = os.path.expanduser("~/.agent/model_profiles.yaml")
		# The fallback seed is at the project root
		seed_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "model_profiles.yaml.example")

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
