"""
TST-VP-001: VramProbe — Hardware-Agnostic Free VRAM Detection
=============================================================
Tests for `red_pill.core.vram_probe.VramProbe`:
  - Backend detection: CUDA (nvidia-smi present), ROCm (sysfs), CPU fallback
  - NVIDIA free VRAM parsing: normal, multi-GPU (takes first), parse error
  - AMD sysfs VRAM calculation: total - used, uevent filter, read error
  - Graceful fallback to 0 MB on any exception
  - get_free_mb() delegates to the correct backend method

All tests are hermetic: no GPU required, no subprocess side-effects.
"""

from unittest.mock import patch

# ── Tests: get_backend ────────────────────────────────────────────────────────

class TestGetBackend:
	def test_cuda_when_nvidia_smi_present(self):
		"""If nvidia-smi is on PATH, backend must be 'cuda'."""
		from red_pill.core.vram_probe import VramProbe
		with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
			assert VramProbe.get_backend() == "cuda"

	def test_rocm_when_amdgpu_sysfs_present(self, tmp_path):
		"""If nvidia-smi absent but AMD DRM card exists, backend must be 'rocm'."""
		from red_pill.core.vram_probe import VramProbe

		# Build a minimal fake /sys/class/drm/card0/device/gpu_busy_percent
		card = tmp_path / "card0" / "device"
		card.mkdir(parents=True)
		(card / "gpu_busy_percent").write_text("42")

		with patch("shutil.which", return_value=None):
			with patch("os.path.isdir", return_value=True):
				with patch("os.listdir", return_value=["card0"]):
					with patch("os.path.exists", return_value=True):
						assert VramProbe.get_backend() == "rocm"

	def test_cpu_when_no_gpu_found(self):
		"""If neither nvidia-smi nor AMD DRM card exists, backend must be 'cpu'."""
		from red_pill.core.vram_probe import VramProbe
		with patch("shutil.which", return_value=None):
			with patch("os.path.isdir", return_value=False):
				assert VramProbe.get_backend() == "cpu"


# ── Tests: _nvidia_free_mb ────────────────────────────────────────────────────

class TestNvidiaFreeMb:
	def test_parses_single_gpu(self):
		"""Single-GPU system: parses memory.free correctly."""
		from red_pill.core.vram_probe import VramProbe
		with patch("subprocess.check_output", return_value=b"6144\n"):
			assert VramProbe._nvidia_free_mb() == 6144

	def test_takes_first_gpu_in_multi_gpu(self):
		"""Multi-GPU: must return only the first GPU's free VRAM."""
		from red_pill.core.vram_probe import VramProbe
		with patch("subprocess.check_output", return_value=b"6144\n2048\n"):
			assert VramProbe._nvidia_free_mb() == 6144

	def test_returns_zero_on_subprocess_error(self):
		"""If nvidia-smi fails (CalledProcessError), must return 0."""
		import subprocess

		from red_pill.core.vram_probe import VramProbe
		with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "nvidia-smi")):
			assert VramProbe._nvidia_free_mb() == 0

	def test_returns_zero_on_parse_error(self):
		"""If output cannot be parsed as int, must return 0."""
		from red_pill.core.vram_probe import VramProbe
		with patch("subprocess.check_output", return_value=b"N/A\n"):
			assert VramProbe._nvidia_free_mb() == 0


# ── Tests: _amd_free_mb ───────────────────────────────────────────────────────

class TestAmdFreeMb:
	def _make_sysfs(self, tmp_path, vram_total_bytes: int, vram_used_bytes: int, is_amdgpu: bool = True):
		"""Creates a minimal fake DRM sysfs tree."""
		device_dir = tmp_path / "card0" / "device"
		device_dir.mkdir(parents=True)
		(device_dir / "gpu_busy_percent").write_text("50")
		if is_amdgpu:
			(device_dir / "uevent").write_text("DRIVER=amdgpu\n")
		else:
			(device_dir / "uevent").write_text("DRIVER=i915\n")
		(device_dir / "mem_info_vram_total").write_text(str(vram_total_bytes))
		(device_dir / "mem_info_vram_used").write_text(str(vram_used_bytes))
		return tmp_path

	def test_calculates_free_correctly(self, tmp_path):
		"""8 GB total - 2 GB used = 6144 MB free. Uses real sysfs tree in tmp_path."""
		import red_pill.core.vram_probe as vp
		from red_pill.core.vram_probe import VramProbe

		drm_root = self._make_sysfs(
			tmp_path,
			vram_total_bytes=8 * 1024 * 1024 * 1024,
			vram_used_bytes=2 * 1024 * 1024 * 1024,
		)

		# Patch the DRM_ROOT constant inside vram_probe to our tmp tree
		with patch.object(vp, "VramProbe") as _mock:
			pass  # just ensure import works

		# Direct: call _amd_free_mb with the tmp drm root by replacing the module constant
		original = getattr(vp, "_DRM_ROOT", "/sys/class/drm")
		try:
			vp._DRM_ROOT = str(drm_root)  # type: ignore[attr-defined]
			result = VramProbe._amd_free_mb()
		finally:
			vp._DRM_ROOT = original  # type: ignore[attr-defined]

		# 8 GB - 2 GB = 6 GB = 6144 MB
		assert result == 6144

	def test_returns_zero_on_read_error(self):
		"""If sysfs read fails, must return 0."""
		from red_pill.core.vram_probe import VramProbe
		with patch("os.path.isdir", return_value=True):
			with patch("os.listdir", side_effect=PermissionError("no access")):
				assert VramProbe._amd_free_mb() == 0


# ── Tests: get_free_mb dispatching ────────────────────────────────────────────

class TestGetFreeMb:
	def test_delegates_to_nvidia_on_cuda_backend(self):
		"""get_free_mb() must call _nvidia_free_mb() when backend is 'cuda'."""
		from red_pill.core.vram_probe import VramProbe
		with patch.object(VramProbe, "get_backend", return_value="cuda"):
			with patch.object(VramProbe, "_nvidia_free_mb", return_value=5000) as mock_nv:
				result = VramProbe.get_free_mb()
		assert result == 5000
		mock_nv.assert_called_once()

	def test_delegates_to_amd_on_rocm_backend(self):
		"""get_free_mb() must call _amd_free_mb() when backend is 'rocm'."""
		from red_pill.core.vram_probe import VramProbe
		with patch.object(VramProbe, "get_backend", return_value="rocm"):
			with patch.object(VramProbe, "_amd_free_mb", return_value=3000) as mock_amd:
				result = VramProbe.get_free_mb()
		assert result == 3000
		mock_amd.assert_called_once()

	def test_returns_zero_on_cpu_backend(self):
		"""get_free_mb() must return 0 when backend is 'cpu'."""
		from red_pill.core.vram_probe import VramProbe
		with patch.object(VramProbe, "get_backend", return_value="cpu"):
			result = VramProbe.get_free_mb()
		assert result == 0

	def test_result_is_always_int(self):
		"""get_free_mb() must always return an int, never float."""
		from red_pill.core.vram_probe import VramProbe
		with patch.object(VramProbe, "get_backend", return_value="cpu"):
			assert isinstance(VramProbe.get_free_mb(), int)
