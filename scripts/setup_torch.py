#!/usr/bin/env python3
"""
setup_torch.py — Auto-detect CUDA version and install matching PyTorch wheel.

Modes:
	(default)      Detect system CUDA and install the right torch wheel.
	--check        Only check for mismatch. Exit 1 + pain signal if mismatch found.
	--auto-fix     If mismatch detected, reinstall the correct wheel automatically.

CUDA → wheel tag discovery (pytorch.org/get-started/locally):
	- Dynamically detects system CUDA via nvcc/nvidia-smi/filesystem.
	- Projects `cuXXX` tag and verifies existence on pytorch.org.
	- Falls back to highest supported stable version if projection fails.
	- No CPU / old → cpu

Called by install_neo.sh after `uv sync`.
Also callable from the Lazarus Pulse for drift detection (--check).
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from red_pill.core.paths import get_config_dir

env_path = get_config_dir() / ".env"
if env_path.exists():
	load_dotenv(env_path)
else:
	load_dotenv()


# CUDA detection


def _get_cuda_version() -> tuple[int, int] | None:
	"""
	Return (major, minor) of the system CUDA version.
	Prioritizes nvidia-smi (Runtime) and torch (Active), then nvcc (Compiler).
	"""
	# 1. Try torch (already loaded or via subprocess)
	try:
		# Use a subprocess to check the environment torch's view of CUDA
		cmd = [sys.executable, "-c", "import torch; print(torch.version.cuda)"]
		out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
		match = re.search(r"(\d+)\.(\d+)", out)
		if match:
			return int(match.group(1)), int(match.group(2))
	except Exception:
		pass

	# 2. Try nvidia-smi (Driver/Runtime version)
	if shutil.which("nvidia-smi"):
		try:
			out = subprocess.check_output(["nvidia-smi"], text=True)
			match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
			if match:
				return int(match.group(1)), int(match.group(2))
		except Exception:
			pass

	# 3. Try nvcc (Compiler version)
	if shutil.which("nvcc"):
		try:
			out = subprocess.check_output(["nvcc", "--version"], text=True)
			match = re.search(r"release (\d+)\.(\d+)", out)
			if match:
				return int(match.group(1)), int(match.group(2))
		except Exception:
			pass

	# 3. Filesystem scan (/usr/local/cuda symlink or directories)
	cuda_paths = ["/usr/local/cuda/version.txt", "/usr/local/cuda/version.json"]
	for p in cuda_paths:
		path = Path(p)
		if path.exists():
			try:
				content = path.read_text()
				match = re.search(r"CUDA Version (\d+)\.(\d+)", content)
				if match:
					return int(match.group(1)), int(match.group(2))
			except Exception:
				pass

	# 4. Fallback search in /usr/local
	try:
		for d in Path("/usr/local").glob("cuda-*"):
			if d.is_dir():
				name = d.name
				# Extract version from 'cuda-12.6'
				match = re.search(r"cuda-(\d+)\.(\d+)", name)
				if match:
					return int(match.group(1)), int(match.group(2))
	except Exception:
		pass

	return None


def _check_url_exists(url: str) -> bool:
	"""Verify if a pytorch.org wheel index exists via HTTP HEAD/GET."""
	try:
		# Use curl if available for speed and simplicity
		if shutil.which("curl"):
			res = subprocess.run(["curl", "-L", "-s", "-I", url], capture_output=True, text=True, timeout=5)
			# Look for "200" in the first few lines
			return "200" in res.stdout.splitlines()[0]

		# Python fallback
		import urllib.request

		req = urllib.request.Request(url, method="HEAD")
		with urllib.request.urlopen(req, timeout=5) as response:
			return response.status == 200
	except Exception:
		return False


def _cuda_to_index(major: int, minor: int) -> str:
	"""
	Map detected CUDA version to the best available cuXXX tag.
	Now performs dynamic probing of the PyTorch index to find the nearest match.
	"""
	# Priority 1: Exact match (e.g., cu130 for CUDA 13.0)
	projected = f"cu{major}{minor}"
	url = f"https://download.pytorch.org/whl/{projected}"

	print(f"[setup_torch] Probing exact index: {url} ...")
	if _check_url_exists(url):
		print(f"[setup_torch] Using exact match: {projected}")
		return projected

	# Priority 2: Dynamic Back-off (Trial & Error)
	# Iterates backward from the detected minor/major to find the next available wheel.
	print("[setup_torch] Exact index unavailable. Starting dynamic back-off probe...")

	# Common major versions to probe if exact fails
	PROBE_MAJORS = sorted(list(set([major, 12, 11])), reverse=True)
	# Common minor versions used by PyTorch
	PROBE_MINORS = [8, 6, 4, 1, 0]

	for v_major in PROBE_MAJORS:
		for v_minor in PROBE_MINORS:
			# Skip versions newer than system (safety)
			if v_major == major and v_minor > minor:
				continue
			tag = f"cu{v_major}{v_minor}"
			test_url = f"https://download.pytorch.org/whl/{tag}"
			if _check_url_exists(test_url):
				print(f"[setup_torch] Found nearest compatible index: {tag} (at {test_url})")
				return tag

	# Priority 3: Common stable targets as a last-resort safety net
	SAFE_FALLBACKS = ["cu124", "cu121", "cu118"]
	for tag in SAFE_FALLBACKS:
		if _check_url_exists(f"https://download.pytorch.org/whl/{tag}"):
			print(f"[setup_torch] Falling back to verified stable index: {tag}")
			return tag

	print("[setup_torch] No CUDA indices found on pytorch.org. Falling back to CPU.")
	return "cpu"


# Installed torch inspection


def _get_installed_torch_cuda_tag() -> str | None:
	"""
	Return the CUDA tag of the currently installed torch wheel
	(e.g. 'cu126', 'cu118', 'cpu'). Returns None if torch is not installed
	or if it fails to import (smoke test).
	"""
	try:
		# We use a subprocess to avoid polluting the current process or crashing it
		# and to get the actual __version__ which is more reliable than metadata.
		cmd = [sys.executable, "-c", "import torch; print(f'{torch.__version__}|{torch.version.cuda}')"]
		res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
		if res.returncode != 0:
			# Try fallback importlib metadata just in case
			import importlib.metadata

			dist = importlib.metadata.distribution("torch")
			v = dist.metadata["version"]
			return v.split("+")[1] if "+" in v else "cpu"

		v_full, cuda_val = res.stdout.strip().split("|")
		if "+" in v_full:
			return v_full.split("+")[1]
		if cuda_val and cuda_val != "None":
			return f"cu{cuda_val.replace('.', '')}"
		return "cpu"
	except Exception:
		return None


# Optional pain signal injection


def _inject_pain_signal(message: str, intensity: float = 7.0) -> None:
	"""Inject a pain signal into signal_memories if Qdrant is reachable."""
	try:
		import hashlib
		import os
		import uuid

		from qdrant_client import QdrantClient
		from qdrant_client.models import Distance, PointStruct, VectorParams

		host = os.getenv("QDRANT_HOST", "localhost")
		port = int(os.getenv("QDRANT_PORT", "6333"))
		api_key = os.getenv("QDRANT_API_KEY")
		client = QdrantClient(host=host, port=port, api_key=api_key, https=False)

		cols = [c.name for c in client.get_collections().collections]
		if "signal_memories" not in cols:
			client.create_collection(
				"signal_memories",
				vectors_config=VectorParams(size=384, distance=Distance.COSINE),
			)

		# Consistent hashing with MemoryManager protocol
		sig_name = "torch_cuda_mismatch"
		sig_hash = hashlib.sha256(sig_name.encode("utf-8")).hexdigest()
		point_id = str(uuid.UUID(sig_hash[:32]))

		client.upsert(
			collection_name="signal_memories",
			points=[
				PointStruct(
					id=point_id,
					vector=[0.0] * 384,
					payload={
						"content": f"[PAIN] {message}",
						"intensity": intensity,
						"immune": False,
					},
				)
			],
		)
		print(f"[setup_torch] Pain signal injected: {message}")
	except Exception as e:
		print(f"[setup_torch] Could not inject pain signal: {e}")


def _clear_pain_signal(signal_id_name: str) -> None:
	"""Remove a pain signal from signal_memories if it exists."""
	try:
		import hashlib
		import os
		import uuid

		from qdrant_client import QdrantClient

		host = os.getenv("QDRANT_HOST", "localhost")
		port = int(os.getenv("QDRANT_PORT", "6333"))
		api_key = os.getenv("QDRANT_API_KEY")
		client = QdrantClient(host=host, port=port, api_key=api_key, https=False)

		# Consistent hashing with MemoryManager protocol
		sig_hash = hashlib.sha256(signal_id_name.encode("utf-8")).hexdigest()
		point_id = str(uuid.UUID(sig_hash[:32]))

		cols = [c.name for c in client.get_collections().collections]
		if "signal_memories" in cols:
			client.delete(
				collection_name="signal_memories",
				points_selector=[point_id],
			)
			print(f"[setup_torch] Pain signal cleared: {signal_id_name}")
	except Exception:
		pass


# Main


def main() -> None:
	parser = argparse.ArgumentParser(description="PyTorch CUDA auto-setup and drift detector.")
	parser.add_argument(
		"--check",
		action="store_true",
		help="Only check for CUDA/torch mismatch. Exit 1 + inject pain signal if mismatch.",
	)
	parser.add_argument(
		"--auto-fix",
		action="store_true",
		help="If mismatch detected in --check mode, automatically reinstall the correct wheel.",
	)
	args = parser.parse_args()

	cuda = _get_cuda_version()
	system_tag = _cuda_to_index(*cuda) if cuda else "cpu"
	cuda_str = f"{cuda[0]}.{cuda[1]}" if cuda else "none"

	# ── Check / drift-detection mode ──────────────────────────────────────
	if args.check or args.auto_fix:
		installed_tag = _get_installed_torch_cuda_tag()

		# Robust check for actual CUDA availability
		try:
			is_cuda_avail = (
				subprocess.run([sys.executable, "-c", "import torch; exit(0 if torch.cuda.is_available() else 1)"], timeout=10).returncode == 0
			)
		except Exception:
			is_cuda_avail = False

		if installed_tag is None:
			print("[setup_torch] ⚠️  torch is not installed or is broken.")
			if not args.auto_fix:
				_inject_pain_signal("torch not installed/broken — run: uv run python scripts/setup_torch.py")
				sys.exit(1)
			print("[setup_torch] --auto-fix: proceeding to fresh installation...")
		elif installed_tag == system_tag:
			print(f"[setup_torch] ✅ torch ({installed_tag}) matches system CUDA {cuda_str}. No action needed.")
			_clear_pain_signal("torch_cuda_mismatch")
			_clear_pain_signal("cuda_cortex_failure")
			return
		elif is_cuda_avail:
			# Available but tag is different (e.g. cu130 vs cu124/cu121)
			print(f"[setup_torch] ✅ torch ({installed_tag}) differs from detected CUDA {cuda_str}, but CUDA is AVAILABLE. Skipping re-install.")
			_clear_pain_signal("torch_cuda_mismatch")
			_clear_pain_signal("cuda_cortex_failure")
			return
		else:
			# Mismatch AND not available
			msg = (
				f"torch CUDA mismatch detected AND NOT AVAILABLE — installed: {installed_tag}, "
				f"system requires: {system_tag} (CUDA {cuda_str}). "
				f"Run: uv run python scripts/setup_torch.py"
			)
			print(f"[setup_torch] ⚠️  {msg}")
			_inject_pain_signal(f"torch_cuda_mismatch: {msg}", intensity=7.0)

			if not args.auto_fix:
				sys.exit(1)

			print("[setup_torch] --auto-fix: reinstalling correct torch wheel...")
		# Fall through to install section below

	# ── Install / reinstall ───────────────────────────────────────────────
	if cuda is None:
		print("[setup_torch] No NVIDIA GPU detected — installing CPU-only torch.")
	else:
		print(f"[setup_torch] System CUDA {cuda_str} → wheel tag: {system_tag}")

	index_url = "https://download.pytorch.org/whl/cpu" if system_tag == "cpu" else f"https://download.pytorch.org/whl/{system_tag}"

	print(f"[setup_torch] Installing torch from {index_url} ...")
	uv_path = shutil.which("uv") or "uv"
	install_cmd = [uv_path, "pip", "install", "torch", "--index-url", index_url]

	# Detect if we should use --system (if not in a venv)
	if not (hasattr(sys, "real_prefix") or (sys.base_prefix != sys.prefix)):
		# Not in a venv, if it's uv we might need --system depending on environment
		# But on Silverblue/OSTree --system will fail unless in a toolbx.
		# For now, let's just try to be more descriptive.
		print("[setup_torch] ⚠️  Not in a virtual environment. uv might require --system.")
		# install_cmd.append("--system")

	result = subprocess.run(install_cmd, check=False)

	if result.returncode == 0:
		print(f"[setup_torch] ✅ torch installed successfully ({system_tag}).")
	else:
		print(f"[setup_torch] ❌ Installation failed (exit {result.returncode}).")
		sys.exit(1)


if __name__ == "__main__":
	main()
