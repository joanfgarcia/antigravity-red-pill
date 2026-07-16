"""Thread-weaving state: the last hub_id per collection across sleep cycles.

Extracted from sleep.py per ADR-SLEEP-001 (the God-Class decomposition, triggered
at >1200 LOC). Pure persistence — no LLM, no GPU.
"""

import json
import logging

from red_pill.core.paths import get_thread_state_path

logger = logging.getLogger(__name__)


def _load_thread_state() -> dict:
	"""Load the last hub_id per collection for inter-session thread weaving."""
	try:
		path = get_thread_state_path()
		if path.exists():
			with open(path) as f:
				return dict(json.load(f))
	except Exception:
		pass
	return {}


def _save_thread_state(state: dict) -> None:
	"""Persist the last hub_id per collection."""
	try:
		path = get_thread_state_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w") as f:
			json.dump(state, f)
	except Exception as e:
		logger.warning(f"[THREAD WEAVER] Could not save thread state: {e}")
