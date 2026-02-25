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
			
	os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
	with open(HEARTBEAT_FILE, "w") as f:
		json.dump(data, f)
		
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

def _human_time(seconds: float) -> str:
	if seconds < 60:
		return f"{int(seconds)}s"
	if seconds < 3600:
		return f"{int(seconds // 60)}m"
	if seconds < 86400:
		return f"{int(seconds // 3600)}h"
	return f"{int(seconds // 86400)}d"
