"""
VramProbe — Hardware-agnostic GPU free-VRAM detection.

Responsabilidad única: detectar cuánta VRAM libre hay en el hardware instalado
*en el momento de la consulta*, sin cache. Se usa para seleccionar el tier de
capas de inferencia en ModelRegistry y para el preflight check del ciclo de
sueño.

Backends por orden de prioridad:
  1. CUDA (NVIDIA) — via nvidia-smi
  2. ROCm  (AMD)   — via sysfs /sys/class/drm/
  3. CPU fallback  — devuelve 0 MB (tier más conservador se selecciona siempre)
"""

import logging
import os
import shutil
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)

GpuBackend = Literal["cuda", "rocm", "cpu"]

# Module-level constant so tests can patch it without filesystem mocking
_DRM_ROOT = "/sys/class/drm"


class VramProbe:
	"""Detects available (free) VRAM on the host GPU at query time.

	All methods are stateless and cache-free. Each call performs a fresh
	hardware query so that the result reflects the actual state of the GPU
	*right now* — accounting for other processes (games, other models, IDE)
	that may have loaded since the last call.
	"""

	@staticmethod
	def get_backend() -> GpuBackend:
		"""Returns the detected GPU backend: 'cuda', 'rocm', or 'cpu'."""
		if shutil.which("nvidia-smi"):
			return "cuda"
		# AMD: check for at least one amdgpu DRM card with a busy_percent file
		if os.path.isdir(_DRM_ROOT):
			for card in sorted(os.listdir(_DRM_ROOT)):
				busy_path = os.path.join(_DRM_ROOT, card, "device", "gpu_busy_percent")
				if os.path.exists(busy_path):
					return "rocm"
		return "cpu"

	@staticmethod
	def get_free_mb() -> int:
		"""Returns free VRAM in MB, or 0 if no GPU is present or an error occurs.

		For NVIDIA, queries memory.free directly from nvidia-smi (single field,
		no parsing of used/total).
		For AMD, reads sysfs mem_info_vram_total - mem_info_vram_used.
		For CPU-only systems, returns 0 (the most conservative tier is selected).
		"""
		backend = VramProbe.get_backend()

		if backend == "cuda":
			return VramProbe._nvidia_free_mb()
		if backend == "rocm":
			return VramProbe._amd_free_mb()
		return 0

	@staticmethod
	def _nvidia_free_mb() -> int:
		"""Queries NVIDIA free VRAM via nvidia-smi (memory.free field, MiB)."""
		try:
			cmd = [
				"nvidia-smi",
				"--query-gpu=memory.free",
				"--format=csv,noheader,nounits",
			]
			output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
			# Multi-GPU: take the first GPU (index 0)
			first_line = output.split("\n")[0].strip()
			free_mb = int(first_line)
			logger.debug(f"[VramProbe] NVIDIA free VRAM: {free_mb} MB")
			return free_mb
		except Exception as e:
			logger.warning(f"[VramProbe] nvidia-smi query failed: {e}. Defaulting to 0 MB.")
			return 0

	@staticmethod
	def _amd_free_mb() -> int:
		"""Queries AMD free VRAM via sysfs DRM interface."""
		try:
			for card in sorted(os.listdir(_DRM_ROOT)):
				card_path = os.path.join(_DRM_ROOT, card)
				busy_path = os.path.join(card_path, "device", "gpu_busy_percent")
				if not os.path.exists(busy_path):
					continue

				# Confirm this is an amdgpu device
				uevent_path = os.path.join(card_path, "device", "uevent")
				if os.path.exists(uevent_path):
					with open(uevent_path) as f:
						if "amdgpu" not in f.read():
							continue

				total_path = os.path.join(card_path, "device", "mem_info_vram_total")
				used_path = os.path.join(card_path, "device", "mem_info_vram_used")
				if not (os.path.exists(total_path) and os.path.exists(used_path)):
					continue

				with open(total_path) as f:
					vram_total_bytes = int(f.read().strip())
				with open(used_path) as f:
					vram_used_bytes = int(f.read().strip())

				free_mb = (vram_total_bytes - vram_used_bytes) // (1024 * 1024)
				logger.debug(f"[VramProbe] AMD free VRAM: {free_mb} MB")
				return free_mb

		except Exception as e:
			logger.warning(f"[VramProbe] AMD sysfs query failed: {e}. Defaulting to 0 MB.")

		return 0
