#!/usr/bin/env python3
"""
setup_torch.py — Auto-detect CUDA version and install matching PyTorch wheel.

Modes:
  (default)      Detect system CUDA and install the right torch wheel.
  --check        Only check for mismatch. Exit 1 + pain signal if mismatch found.
  --auto-fix     If mismatch detected, reinstall the correct wheel automatically.

CUDA → wheel tag map (pytorch.org/get-started/locally):
  CUDA ≥ 12.6  → cu126  (RTX 5070 / Blackwell, driver 580+)
  CUDA ≥ 12.4  → cu124
  CUDA ≥ 12.1  → cu121
  CUDA ≥ 11.8  → cu118
  No GPU / old → cpu

Called by install_neo.sh after `uv sync`.
Also callable from the Lazarus Pulse for drift detection (--check).
"""

import argparse
import re
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# CUDA detection
# ---------------------------------------------------------------------------

def _get_cuda_version() -> tuple[int, int] | None:
	"""
	Return (major, minor) of the CUDA runtime supported by the current driver.
	Uses `nvidia-smi` which is always present when an NVIDIA GPU is installed.
	Returns None if no GPU or nvidia-smi is not available.
	"""
	if not shutil.which("nvidia-smi"):
		return None
	try:
		out = subprocess.check_output(["nvidia-smi"], text=True)
		match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
		if match:
			return int(match.group(1)), int(match.group(2))
	except Exception:
		pass

	# Fallback: infer from driver version number
	# Driver 560+ → CUDA 12.6, 545+ → 12.3, 530+ → 12.1, 525+ → 12.0, 520+ → 11.8
	try:
		driver_out = subprocess.check_output(
			["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
			text=True,
		).strip().splitlines()[0].strip()
		major = int(driver_out.split(".")[0])
		if major >= 560:
			return 12, 6
		elif major >= 545:
			return 12, 3
		elif major >= 530:
			return 12, 1
		elif major >= 525:
			return 12, 0
		elif major >= 520:
			return 11, 8
	except Exception:
		pass

	return None


def _cuda_to_index(major: int, minor: int) -> str:
	"""Map CUDA (major, minor) to the pytorch.org wheel tag."""
	v = major * 10 + minor  # 12.6 → 126
	if v >= 126:
		return "cu126"
	elif v >= 124:
		return "cu124"
	elif v >= 121:
		return "cu121"
	elif v >= 118:
		return "cu118"
	else:
		return "cpu"


# ---------------------------------------------------------------------------
# Installed torch inspection
# ---------------------------------------------------------------------------

def _get_installed_torch_cuda_tag() -> str | None:
	"""
	Return the CUDA tag of the currently installed torch wheel
	(e.g. 'cu126', 'cu118', 'cpu'). Returns None if torch is not installed.
	"""
	try:
		import importlib.metadata
		dist = importlib.metadata.distribution("torch")
		version = dist.metadata["version"]  # e.g. "2.11.0+cu126"
		if "+" in version:
			return version.split("+")[1]     # "cu126"
		return "cpu"
	except Exception:
		return None


# ---------------------------------------------------------------------------
# Optional pain signal injection
# ---------------------------------------------------------------------------

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
			points=[PointStruct(
				id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "torch_cuda_mismatch")),
				vector=[0.0] * 384,
				payload={
					"content": f"[PAIN] {message}",
					"intensity": intensity,
					"immune": False,
				},
			)],
		)
		print(f"[setup_torch] Pain signal injected: {message}")
	except Exception as e:
		print(f"[setup_torch] Could not inject pain signal: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
	parser = argparse.ArgumentParser(description="PyTorch CUDA auto-setup and drift detector.")
	parser.add_argument(
		"--check", action="store_true",
		help="Only check for CUDA/torch mismatch. Exit 1 + inject pain signal if mismatch.",
	)
	parser.add_argument(
		"--auto-fix", action="store_true",
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
			print("[setup_torch] ⚠️  torch is not installed.")
			_inject_pain_signal("torch not installed — run: uv run python scripts/setup_torch.py")
			sys.exit(1)

		if installed_tag == system_tag:
			print(f"[setup_torch] ✅ torch ({installed_tag}) matches system CUDA {cuda_str}. No action needed.")
			return

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

	index_url = (
		"https://download.pytorch.org/whl/cpu"
		if system_tag == "cpu"
		else f"https://download.pytorch.org/whl/{system_tag}"
	)

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
