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

load_dotenv()


# CUDA detection


def _get_cuda_version() -> tuple[int, int] | None:
	"""
	Return (major, minor) of the system CUDA version.
	Prioritizes nvcc, fails over to nvidia-smi, then filesystem scan.
	"""
	# 1. Try nvcc (Compiler version)
	if shutil.which("nvcc"):
		try:
			out = subprocess.check_output(["nvcc", "--version"], text=True)
			match = re.search(r"release (\d+)\.(\d+)", out)
			if match:
				return int(match.group(1)), int(match.group(2))
		except Exception:
			pass

	# 2. Try nvidia-smi (Runtime version from driver)
	if shutil.which("nvidia-smi"):
		try:
			out = subprocess.check_output(["nvidia-smi"], text=True)
			match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
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
	Now dynamically projects the tag and verifies the URL.
	"""
	# Known stable indices in descending order
	STABLE_INDICES = ["cu126", "cu124", "cu121", "cu118"]

	# Project tag: 13.0 -> cu130, 12.6 -> cu126
	projected = f"cu{major}{minor}"
	url = f"https://download.pytorch.org/whl/{projected}"

	# 1. Try the exact match first
	print(f"[setup_torch] Verifying projected index: {url} ...")
	if _check_url_exists(url):
		return projected

	# 2. Find the highest stable that is <= the detected version
	v_detected = major * 100 + minor  # 12.4 -> 1204
	for tag in STABLE_INDICES:
		# Parse tag: cu124 -> (12, 4) -> 1204
		m = re.match(r"cu(\d+)(\d)", tag)
		if m:
			v_stable = int(m.group(1)) * 100 + int(m.group(2))
			if v_stable <= v_detected:
				print(f"[setup_torch] ⚠️  {projected} index not found. Falling back to {tag}.")
				return tag

	# 3. Last resort fallback
	return "cpu"


# Installed torch inspection


def _get_installed_torch_cuda_tag() -> str | None:
	"""
	Return the CUDA tag of the currently installed torch wheel
	(e.g. 'cu126', 'cu118', 'cpu'). Returns None if torch is not installed
	or if it fails to import (smoke test).
	"""
	try:
		# 1. Check metadata (fast)
		import importlib.metadata

		dist = importlib.metadata.distribution("torch")
		version = dist.metadata["version"]  # e.g. "2.11.0+cu126"
		tag = version.split("+")[1] if "+" in version else "cpu"

		# 2. Smoke test: actual import (slow but necessary for dynamic link checks)
		# We use a subprocess to avoid polluting the current process or crashing it
		# if there's a serious ImportError/Segfault.
		res = subprocess.run([sys.executable, "-c", "import torch; print(torch.version.cuda)"], capture_output=True, text=True, timeout=10)
		if res.returncode != 0:
			print(f"[setup_torch] ⚠️  Torch exists but failed smoke test: {res.stderr.strip()}")
			return None

		return tag
	except Exception:
		return None


# Optional pain signal injection


def _inject_pain_signal(message: str, intensity: float = 7.0) -> None:
	"""Inject a pain signal into signal_memories if Qdrant is reachable."""
	try:
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

		client.upsert(
			collection_name="signal_memories",
			points=[
				PointStruct(
					id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "torch_cuda_mismatch")),
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

		if installed_tag is None:
			print("[setup_torch] ⚠️  torch is not installed or is broken.")
			if not args.auto_fix:
				_inject_pain_signal("torch not installed/broken — run: uv run python scripts/setup_torch.py")
				sys.exit(1)
			print("[setup_torch] --auto-fix: proceeding to fresh installation...")
		elif installed_tag == system_tag:
			print(f"[setup_torch] ✅ torch ({installed_tag}) matches system CUDA {cuda_str}. No action needed.")
			return
		else:
			# Mismatch
			msg = (
				f"torch CUDA mismatch detected — installed: {installed_tag}, "
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
	result = subprocess.run(
		[uv_path, "pip", "install", "torch", "--index-url", index_url],
		check=False,
	)

	if result.returncode == 0:
		print(f"[setup_torch] ✅ torch installed successfully ({system_tag}).")
	else:
		print(f"[setup_torch] ❌ Installation failed (exit {result.returncode}).")
		sys.exit(1)


if __name__ == "__main__":
	main()
