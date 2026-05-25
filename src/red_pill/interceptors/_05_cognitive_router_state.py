"""
Shared session state for the Casual Override latch.
Both 05_cognitive_router.py and 06_tone_adapter.py read/write here.
Lives in module memory — persists across turns within the same MCP process.
Resets on MCP server restart.
"""

_casual_mode_active: bool = False
_consecutive_non_work_turns: int = 0

# Last emitted state per plugin — used to suppress duplicate injections.
# Only inject when state changes (transition). Otherwise return "".
_last_router_state: str | None = None
_last_tone_state: str | None = None

WORK_KEYWORDS = [
	"arregla",
	"fix",
	"implementa",
	"modo trabajo",
	"trabaja",
	"ejecuta",
	"despliega",
	"haz un",
	"crea un",
	"commit",
	"push",
]


def is_casual_active() -> bool:
	return _casual_mode_active


def set_casual(active: bool) -> None:
	global _casual_mode_active, _consecutive_non_work_turns
	_casual_mode_active = active
	if active:
		_consecutive_non_work_turns = 0


def register_turn(prompt: str, casual_kws: list[str]) -> None:
	"""
	Updates the state of the casual latch based on the current prompt content.
	Implements 'engine braking' (freno de motor): automatically decays work mode
	into casual mode if 2 consecutive turns lack work keywords.
	"""
	global _casual_mode_active, _consecutive_non_work_turns

	prompt_lower = prompt.lower()
	has_work_kws = any(kw in prompt_lower for kw in WORK_KEYWORDS)
	has_casual_kws = any(kw in prompt_lower for kw in casual_kws)

	# If the user explicitly asks to relax/chat, activate casual mode instantly.
	if has_casual_kws:
		set_casual(True)
		return

	# If the prompt has work keywords, reset the non-work turn counter and force work mode.
	if has_work_kws:
		set_casual(False)
		_consecutive_non_work_turns = 0
		return

	# If work mode is active and this prompt lacks work keywords:
	if not _casual_mode_active:
		_consecutive_non_work_turns += 1
		# Cooldown threshold: 2 consecutive turns without work keywords triggers casual mode.
		if _consecutive_non_work_turns >= 2:
			set_casual(True)


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
