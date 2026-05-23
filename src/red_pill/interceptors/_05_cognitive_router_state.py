"""
Shared session state for the Casual Override latch.
Both 05_cognitive_router.py and 06_tone_adapter.py read/write here.
Lives in module memory — persists across turns within the same MCP process.
Resets on MCP server restart.
"""

_casual_mode_active: bool = False

# Last emitted state per plugin — used to suppress duplicate injections.
# Only inject when state changes (transition). Otherwise return "".
_last_router_state: str | None = None
_last_tone_state: str | None = None

WORK_KEYWORDS = [
	"arregla", "fix", "implementa", "modo trabajo", "trabaja",
	"ejecuta", "despliega", "haz un", "crea un", "commit", "push",
]


def is_casual_active() -> bool:
	return _casual_mode_active


def set_casual(active: bool) -> None:
	global _casual_mode_active
	_casual_mode_active = active


def check_transition(plugin: str, current_state: str) -> bool:
	"""Return True if state changed since last emission. Updates tracker."""
	global _last_router_state, _last_tone_state

	if plugin == "router":
		changed = _last_router_state != current_state
		_last_router_state = current_state
		return changed
	elif plugin == "tone":
		changed = _last_tone_state != current_state
		_last_tone_state = current_state
		return changed
	return True

