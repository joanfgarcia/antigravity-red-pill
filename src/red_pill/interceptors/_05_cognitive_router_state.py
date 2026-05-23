"""
Shared session state for the Casual Override latch.
Both 05_cognitive_router.py and 06_tone_adapter.py read/write here.
Lives in module memory — persists across turns within the same MCP process.
Resets on MCP server restart.
"""

_casual_mode_active: bool = False

WORK_KEYWORDS = [
	"arregla", "fix", "implementa", "modo trabajo", "trabaja",
	"ejecuta", "despliega", "haz un", "crea un", "commit", "push",
]


def is_casual_active() -> bool:
	return _casual_mode_active


def set_casual(active: bool) -> None:
	global _casual_mode_active
	_casual_mode_active = active
