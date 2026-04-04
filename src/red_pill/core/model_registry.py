import os
import yaml
import logging

logger = logging.getLogger(__name__)

DEFAULT_PROFILES = {
	"samantha": {
		"model_path": "3rdparty/BitNet-1.58b/models/Llama3-8B-Instruct.gguf",
		"temperature": 0.7,
		"max_tokens": 1024,
		"use_mmap": False,
	},
	"smith": {
		"model_path": "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf",
		"temperature": 0.0,
		"max_tokens": 512,
		"grammar_path": "3rdparty/BitNet-1.58b/validation/json.gbnf",
		"use_mmap": False,
	}
}

class ModelRegistry:
	_profiles_cache = None

	@classmethod
	def get_profile(cls, profile_name: str) -> dict:
		if cls._profiles_cache is None:
			cls._load_profiles()
		return cls._profiles_cache.get(profile_name, {})

	@classmethod
	def _load_profiles(cls):
		config_path = os.path.expanduser("~/.agent/model_profiles.yaml")
		cls._profiles_cache = DEFAULT_PROFILES.copy()
		if os.path.exists(config_path):
			try:
				with open(config_path, "r") as f:
					data = yaml.safe_load(f)
					if data and "profiles" in data:
						cls._profiles_cache.update(data["profiles"])
				logger.info(f"Loaded override model profiles from {config_path}")
			except Exception as e:
				logger.error(f"Failed to load model profiles from {config_path}: {e}")
		else:
			# Create defaults to guide user
			try:
				os.makedirs(os.path.dirname(config_path), exist_ok=True)
				with open(config_path, "w") as f:
					yaml.dump({"profiles": DEFAULT_PROFILES}, f)
			except Exception:
				pass
