import asyncio
import logging
import time
from typing import List

from red_pill.swarm.base import Minion, SwarmResult
from red_pill.utils.observer import notify_user
from red_pill.utils.specs_adapter import SpecsAdapter

logger = logging.getLogger(__name__)


class GruOrchestrator:
	"""
	The Sovereign Orchestrator (Gru).
	Manages the deployment and collection of specialized Minions.
	Integrated with specs.md (v5.6.2) and the Sovereign Alert System (SAS).
	"""

	def __init__(self):
		import os

		from red_pill.core.inbox import MinionInbox

		self.active_minions: List[Minion] = []
		self.workspace_root = os.getcwd()
		self.specs = SpecsAdapter(self.workspace_root)
		self.inbox = MinionInbox()

	def is_local_ready(self) -> bool:
		"""Check if local SLM infrastructure is available."""
		import os

		ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		model_dir = os.path.join(ia_dir, "models")
		if not os.path.exists(model_dir):
			return False
		return any(f.endswith(".gguf") for f in os.listdir(model_dir))

	async def deploy_swarm(self, task: str, minions: List[Minion], **kwargs) -> List[SwarmResult]:
		"""Deploys a swarm of specialized agents with automatic context injection."""

		# 2. Spec-Aware Context Injection
		specs_prefix = ""
		flow = self.specs.detect_flow()
		if flow == "fire":
			intents = self.specs.get_fire_intents()
			if intents:
				specs_prefix = f"[SPECS: FIRE INTENTS]\n{intents}\n---\n"
		elif flow == "simple":
			tasks = self.specs.get_simple_tasks()
			if tasks:
				specs_prefix = f"[SPECS: SIMPLE TASKS]\n{tasks}\n---\n"

		# 3. Enrich the task with specs context
		enriched_task = f"{specs_prefix}{task}" if specs_prefix else task

		# 4. Deploy Minions
		logger.info(f"Deploying swarm to execute: {task[:100]}...")
		tasks_parallel = [self._run_minion(m, enriched_task, **kwargs) for m in minions]
		results = await asyncio.gather(*tasks_parallel)

		# 5. SAS: Sovereign Alert System integration
		self._trigger_sas(task, results)

		return results

	def _trigger_sas(self, task: str, results: List[SwarmResult]) -> None:
		"""Record memory and notify user of swarm completion."""
		success_count = len([r for r in results if r.status == "success"])
		message = f"Swarm Task Complete: {task}. {success_count}/{len(results)} minions succeeded."

		# Sensory Signal (User) - Silent by default per Operator directive
		notify_user(title="Sovereign Swarm", message=message, sound=False, category="swarm")

		import uuid
		import json

		# Memory Signal (Agent) - For Turn-Zero recovery
		try:
			event_id = str(uuid.uuid4())[:8]
			metadata = {
				"type": "swarm_event",
				"task_preview": task[:200],
				"timestamp": time.time(),
				"results_summary": [f"{r.minion_id}: {r.status}" for r in results],
			}
			
			full_content = f"{message}\n\nMetadata: {json.dumps(metadata)}"
			self.inbox.drop_report(event_id=event_id, source="GruOrchestrator", status="success" if success_count > 0 else "failed", content=full_content)
		except Exception as e:
			logger.error(f"SAS Inbox Hook failed: {e}")

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		start = time.time()
		try:
			result = await minion.execute(task, **kwargs)
			return SwarmResult(minion_id=minion.id, status="success", duration=round(time.time() - start, 3), result=result)
		except Exception as e:
			return SwarmResult(minion_id=minion.id, status="failed", duration=round(time.time() - start, 3), result={}, error=str(e))
