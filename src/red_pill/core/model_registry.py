import logging
import os
import shutil
from typing import Dict, Optional

import yaml

from red_pill.core.model_license import ModelLicenseError, assert_commercial_ok, normalize_license
from red_pill.core.paths import get_bunker_root, get_model_profiles_path
from red_pill.core.vram_probe import VramProbe

logger = logging.getLogger(__name__)


class ModelRegistry:
	_profiles_cache: Optional[Dict[str, dict]] = None
	_profiles_mtime: float = 0.0

	@classmethod
	def reload(cls) -> None:
		"""Refresca el cache si el mtime de model_profiles.yaml cambió (RFC-HARNESS-002 §10).

		Hot reload por request: los perfiles añadidos sin restart se detectan
		en la siguiente resolución del selector (`model_runtime._get_profile`).
		Barato: `stat()` ≈ µs; la recarga solo ocurre si el fichero cambió.
		"""
		import os as _os

		try:
			mtime = _os.stat(get_model_profiles_path()).st_mtime
		except OSError:
			return
		if cls._profiles_cache is not None and abs(mtime - cls._profiles_mtime) < 1e-6:
			return
		cls._profiles_cache = None
		cls._load_profiles()
		cls._profiles_mtime = mtime

	@classmethod
	def get_profile(cls, profile_name: str) -> dict:
		if cls._profiles_cache is None:
			cls._load_profiles()
			try:
				import os as _os

				cls._profiles_mtime = _os.stat(get_model_profiles_path()).st_mtime
			except OSError:
				pass
		if cls._profiles_cache is not None:
			return cls._profiles_cache.get(profile_name, {})
		return {}

	@classmethod
	def get_license(cls, profile_name: str) -> dict:
		"""Normalized license policy for a profile (fail-closed if undeclared)."""
		return normalize_license(cls.get_profile(profile_name).get("license"), profile_name)

	@classmethod
	def get_all_profiles(cls) -> dict:
		"""All loaded profiles (forces a load if the cache is cold)."""
		if cls._profiles_cache is None:
			cls._load_profiles()
		return dict(cls._profiles_cache or {})

	@classmethod
	def assert_commercial_ok(cls, profile_name: str, context: str | None = None) -> None:
		"""Gate: raise ModelLicenseError si `profile_name` se usa en contexto comercial.

		No-op si el perfil no existe (el flujo aguas abajo fallará por su cuenta;
		no fabricamos un bloqueo de licencia falso).
		"""
		profile = cls.get_profile(profile_name)
		if not profile:
			return
		assert_commercial_ok(profile.get("license"), model_name=profile_name, context=context)

	@classmethod
	def get_profile_by_capability(
		cls,
		required_capability: str,
		commercial_only: bool = False,
		context: str | None = None,
	) -> tuple[str, dict]:
		"""Find a profile exposing `required_capability`.

		When `commercial_only` is True (e.g. a commercial-context run), profiles
		whose license forbids commercial use are skipped; if every candidate is
		blocked, `ModelLicenseError` is raised instead of silently falling back.
		"""
		if cls._profiles_cache is None:
			cls._load_profiles()
		if cls._profiles_cache is not None:
			blocked: list[str] = []
			for name, profile in cls._profiles_cache.items():
				caps = profile.get("capabilities", [])
				if required_capability in caps:
					if commercial_only:
						try:
							assert_commercial_ok(profile.get("license"), model_name=name, context=context)
						except ModelLicenseError:
							blocked.append(name)
							continue
					return name, profile
			# Fallback to the first available profile if none match exactly
			if cls._profiles_cache:
				first_name = list(cls._profiles_cache.keys())[0]
				if commercial_only:
					try:
						assert_commercial_ok(
							cls._profiles_cache[first_name].get("license"),
							model_name=first_name,
							context=context,
						)
					except ModelLicenseError as e:
						if blocked:
							raise ModelLicenseError(
								f"[LICENSE] Todos los perfiles con capability '{required_capability}' "
								f"están bloqueados en contexto comercial ({', '.join(blocked)}). "
								f"Define un perfil permisivo (Apache-2.0/MIT) para esa capability."
							) from e
						raise
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
		to use that tier. Tiers are sorted ascending; the most demanding tier whose
		min_free_gb is satisfied by the currently free VRAM is selected
		(highest usable). If no tier fits, the most conservative (lowest) is used.

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

		# Sort tiers by min_free_gb ascending. Pick the highest GPU-capable tier
		# whose min_free_gb fits. Tiers with n_gpu_layers=0 are CPU fallback
		# markers — they are NEVER preferred over a GPU tier that fits, even if
		# the CPU tier has the highest min_free_gb threshold. The CPU fallback
		# path is only used when no GPU tier fits (or when there are no GPU
		# tiers at all).
		tiers = sorted(hardware["vram_tiers"], key=lambda x: x.get("min_free_gb", 0))
		gpu_tiers = [t for t in tiers if t.get("n_gpu_layers", 0) != 0]
		cpu_tiers = [t for t in tiers if t.get("n_gpu_layers", 0) == 0]
		matched_tier = None
		for tier in gpu_tiers:
			if free_vram_gb >= tier.get("min_free_gb", 0):
				matched_tier = tier
		if matched_tier is None:
			# No GPU tier fits. Use the most conservative CPU tier as a graceful
			# fallback (slowest but never OOMs due to under-spec).
			if cpu_tiers:
				matched_tier = cpu_tiers[0]
			elif gpu_tiers:
				# No CPU tier defined — fall back to the lowest GPU tier
				# (the least-demanding one, which most often fits).
				matched_tier = gpu_tiers[0]

		if matched_tier:
			logger.info(f"[ModelRegistry] Free VRAM {free_vram_gb:.2f} GB → tier: {matched_tier}")
			for k, v in matched_tier.items():
				if k != "min_free_gb":
					resolved[k] = v

		return resolved

	@classmethod
	def get_max_load_time_s(cls, backend: str = "default") -> int:
		"""Returns the maximum expected load time across all profiles for a given backend.

		Used by the Sentinel to set a model-aware grace period instead of a
		hardcoded constant. Scans all profiles' hardware_affinity.load_time_s
		and returns the worst-case value for the specified backend.

		Falls back to 'default' key if the requested backend is not found
		in a profile, then to MODEL_LOAD_GRACE_FALLBACK_S (180s).
		"""
		MODEL_LOAD_GRACE_FALLBACK_S = 180

		if cls._profiles_cache is None:
			cls._load_profiles()
		if not cls._profiles_cache:
			return MODEL_LOAD_GRACE_FALLBACK_S

		max_time = 0
		for _name, profile in cls._profiles_cache.items():
			hw = profile.get("hardware_affinity", {})
			load_times = hw.get("load_time_s", {})
			if not load_times:
				continue
			t = load_times.get(backend, load_times.get("default", 0))
			if t > max_time:
				max_time = t

		return max_time if max_time > 0 else MODEL_LOAD_GRACE_FALLBACK_S
