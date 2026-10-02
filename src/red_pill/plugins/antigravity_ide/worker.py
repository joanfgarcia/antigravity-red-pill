"""Deprecated shim — the generic worker moved to ``red_pill.core.agent_worker``.

`IDEWorker` and its module-level helpers stopped being Antigravity-specific
(they orchestrate inbox → bridge → outbox, AWAKENINGs, Telegram routing and
Samantha) and now live in the neutral core. This module re-exports them for
backward compatibility so existing imports and tests keep working.

New code should import from ``red_pill.core.agent_worker`` directly.
"""

from red_pill.core import agent_worker as _agent_worker

# Re-export every public and private name so `import ... as worker_module` and
# `from ...worker import X` keep resolving identical objects.
for _name in dir(_agent_worker):
	if not _name.startswith("__"):
		globals()[_name] = getattr(_agent_worker, _name)

__all__ = [_name for _name in dir(_agent_worker) if not _name.startswith("_")]
