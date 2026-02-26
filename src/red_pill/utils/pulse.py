import json
import os
import time
from typing import Dict, Any

import red_pill.config as cfg

HEARTBEAT_FILE = os.path.join(cfg.IA_DIR, "storage", "pulse.json")

def record_interaction() -> Dict[str, Any]:
	"""Records current interaction time and returns cadence stats."""
	now = time.time()
	data = {"last_interaction": now, "prev_interaction": 0.0}

	if os.path.exists(HEARTBEAT_FILE):
		try:
			with open(HEARTBEAT_FILE, "r") as f:
				old_data = json.load(f)
				data["prev_interaction"] = old_data.get("last_interaction", 0.0)
		except Exception:
			pass

	# CQ-004: Atomic write — write to .tmp, then os.replace() (POSIX-atomic rename).
	# Prevents torn reads in concurrent session scenarios: readers always see
	# either the complete old file or the complete new file, never a partial write.
	_atomic_write_heartbeat(data)

	delta = now - data["prev_interaction"] if data["prev_interaction"] > 0 else 0

	status = "normal"
	if data["prev_interaction"] == 0:
		status = "initial"
	elif delta < cfg.CADENCE_BURST_THRESHOLD:
		status = "burst"
	elif delta > cfg.CADENCE_ABSENCE_THRESHOLD:
		status = "dormant"

	return {
		"status": status,
		"delta_seconds": delta,
		"delta_human": _human_time(delta)
	}


def _atomic_write_heartbeat(data: Dict[str, Any]) -> None:
	"""
	Writes heartbeat data atomically to HEARTBEAT_FILE.

	Pattern: write to <HEARTBEAT_FILE>.tmp → os.replace() → HEARTBEAT_FILE.
	os.replace() is guaranteed atomic on POSIX (same filesystem).
	"""
	heartbeat_dir = os.path.dirname(HEARTBEAT_FILE)
	os.makedirs(heartbeat_dir, exist_ok=True)

	tmp_path = HEARTBEAT_FILE + ".tmp"
	try:
		with open(tmp_path, "w") as f:
			json.dump(data, f)
			f.flush()
			os.fsync(f.fileno())   # Flush kernel buffers to disk before rename
		os.replace(tmp_path, HEARTBEAT_FILE)
	except Exception:
		# Best-effort cleanup of temp file on failure
		try:
			os.unlink(tmp_path)
		except OSError:
			pass
		raise


def _human_time(seconds: float) -> str:
	if seconds < 60:
		return f"{int(seconds)}s"
	if seconds < 3600:
		return f"{int(seconds // 60)}m"
	if seconds < 86400:
		return f"{int(seconds // 3600)}h"
	return f"{int(seconds // 86400)}d"

