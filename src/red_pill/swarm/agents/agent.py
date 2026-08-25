"""
AgentMinion — first-class swarm minion that delegates a task to an external
agent backend (agy / claude / local) via the AgentBridge abstraction.

Promotes the autonomous executor path (swarm/executor.py) to a registered Minion:
the swarm/orchestrator/cognitive-queue can now treat "run an agent" like any other
minion. `kwargs['backend']` selects the bridge (default: IDE_BACKEND config).
"""

import asyncio
import time
from typing import Any, Dict

from red_pill.swarm.base import Minion


class AgentMinion(Minion):
	"""Minion that runs a task through an agent backend (agy/claude/local)."""

	name: str = "Agent-Runner"
	specialization: str = "Agentic Task Execution"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		"""Delegate `task` to an agent backend via AgentBridge.prompt().

		kwargs:
			backend: "agy" | "claude" | "local" | None (None → IDE_BACKEND config)
			model:   backend-specific model hint (default "flash")
			effort:  reasoning-effort hint (low|medium|high|xhigh|max); backend may ignore
			cwd/workspace: working dir the agent operates in (target project)
			timeout: seconds (default 300)
		"""
		backend = kwargs.get("backend")
		model = kwargs.get("model", "flash")
		effort = kwargs.get("effort")
		cwd = kwargs.get("cwd") or kwargs.get("workspace")
		timeout = int(kwargs.get("timeout", 300))
		origin = kwargs.get("origin")
		self.log(f"Delegando a agente (backend={backend or 'config'}): {task[:60]}...")
		start = time.time()

		try:
			import red_pill.config as cfg

			bridge_kwargs: Dict[str, Any] = {}
			if origin is not None:
				bridge_kwargs["origin"] = origin

			if backend is None:
				from red_pill.swarm.bridges import create_cascade_bridge

				bridge = create_cascade_bridge(
					cfg.get_config().DEFAULT_MINION_BRIDGE_CASCADE,
					name="DEFAULT_MINION_BRIDGE_CASCADE",
					**bridge_kwargs,
				)
			else:
				from red_pill.swarm.bridges import create_bridge

				bridge = create_bridge(backend, **bridge_kwargs)
			# bridge.prompt is a blocking subprocess call — run off the event loop.
			result = await asyncio.to_thread(bridge.prompt, task, model=model, effort=effort, cwd=cwd, timeout=timeout)
		except Exception as e:
			return {"status": "error", "error": str(e), "duration": time.time() - start}

		return {
			"status": "success" if result.ok else "failed",
			"response": result.response,
			"conversation_id": result.conversation_id,
			"backend": backend or "config",
			"error": result.error,
			"duration": time.time() - start,
		}
