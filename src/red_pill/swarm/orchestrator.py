import asyncio
import logging
import time
from typing import List, Union

from red_pill.swarm.base import Minion, SwarmResult
from red_pill.utils.observer import notify_user
from red_pill.utils.specs_adapter import SpecsAdapter
from red_pill.swarm.flow_engine import FlowEngine
from red_pill.swarm.factory import MinionFactory
from red_pill.config import FLOW_REGISTRY_PATH

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
		self.flow_engine = FlowEngine(FLOW_REGISTRY_PATH)

	def is_local_ready(self) -> bool:
		"""Check if local SLM infrastructure is available."""
		import os

		ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		model_dir = os.path.join(ia_dir, "models")
		if not os.path.exists(model_dir):
			return False
		return any(f.endswith(".gguf") for f in os.listdir(model_dir))

	async def deploy_swarm(self, task: str, minions: List[Union[Minion, str]], trace: bool = True, **kwargs) -> List[SwarmResult]:
		"""Deploys a swarm of specialized agents with automatic context injection."""
		
		# 1. Resolve string IDs to Minion objects
		resolved_minions = []
		for m in minions:
			if isinstance(m, str):
				obj = MinionFactory.create(m, **kwargs)
				if obj:
					resolved_minions.append(obj)
				else:
					logger.error(f"Failed to resolve minion ID: {m}")
			else:
				resolved_minions.append(m)

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
		logger.info(f"Deploying swarm to execute: {task[:100] if isinstance(task, str) else 'task'}...")
		tasks_parallel = [self._run_minion(m, enriched_task, **kwargs) for m in resolved_minions]
		results = await asyncio.gather(*tasks_parallel)

		# 5. SAS: Sovereign Alert System integration (Selective Tracing)
		if trace:
			self._trigger_sas(task, results)
		else:
			logger.debug(f"Swarm task finished successfully (Traces suppressed): {task[:50]}")

		return results

	def _trigger_sas(self, task: str, results: List[SwarmResult]) -> None:
		"""Record memory and notify user of swarm completion."""
		success_count = len([r for r in results if r.status == "success"])
		task_preview = task[:100] if isinstance(task, str) else "task"
		message = f"Swarm Task Complete: {task_preview}. {success_count}/{len(results)} minions succeeded."

		# Sensory Signal (User) - Silent by default per Operator directive
		notify_user(title="Sovereign Swarm", message=message, sound=False, category="swarm")

		import json
		import uuid

		# Memory Signal (Agent) - For Turn-Zero recovery
		try:
			event_id = str(uuid.uuid4())[:8]
			task_str = str(task)
			metadata = {
				"type": "swarm_event",
				"task_preview": task_str[:200],
				"timestamp": time.time(),
				"results_summary": [f"{r.minion_id}: {r.status}" for r in results],
			}

			full_content = f"{message}\n\nMetadata: {json.dumps(metadata)}"
			self.inbox.drop_report(
				event_id=event_id, source="GruOrchestrator", status="success" if success_count > 0 else "failed", content=full_content
			)
		except Exception as e:
			logger.error(f"SAS Inbox Hook failed: {e}")

	async def run_autonomous_flow(self, flow_id: str, **kwargs) -> List[SwarmResult]:
		"""
		Loads a predefined flow template and executes its minions sequentially.
		Supports flow-level 'on_fail' policies.
		"""
		flow = self.flow_engine.get_flow(flow_id, self.workspace_root)
		if not flow:
			raise ValueError(f"Flow '{flow_id}' not found in global or local registries.")

		logger.info(f"🚀 INICIANDO FLUJO AUTÓNOMO: {flow.get('name', flow_id)}")

		overall_results = []
		for step in flow.get("steps", []):
			minion_id = step.get("minion")
			on_fail = step.get("on_fail", "warn")
			delegate_to = step.get("delegate_to") # Enterprise: handover to another agent

			# 1. Handover Check (Simulated for Enterprise meeting)
			if delegate_to:
				logger.info(f"🤝 [ENTERPRISE] Delegando paso a agente externo: {delegate_to}")
				# En una implementación real, aquí emitiríamos un SwarmMessage y esperaríamos
				# Por ahora, simulamos una delegación exitosa con un resultado dummy
				overall_results.append(SwarmResult(
					minion_id=f"remote_{delegate_to}", 
					status="pending_approval", 
					duration=0.0, 
					result={"msg": f"Handover sent to {delegate_to}"}
				))
				continue

			# 2. Local Minion execution
			minion = MinionFactory.create(minion_id)
			if not minion:
				logger.error(f"Minion '{minion_id}' could not be instantiated.")
				continue

			# Deploy as a single-minion swarm to maintain SAS/Inbox consistency
			# Passing the flow description as the task context
			step_task = f"Execute {minion_id} for Flow: {flow_id}"
			results = await self.deploy_swarm(task=step_task, minions=[minion], **kwargs)
			overall_results.extend(results)

			# Flow Control: on_fail policies
			if any(r.status == "failed" for r in results):
				if on_fail in ("stop", "abort"):
					logger.warning(f"🛑 Flujo abortado por fallo en '{minion_id}'. Política: {on_fail}")
					break

		return overall_results

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		start = time.time()
		try:
			result = await minion.execute(task, **kwargs)
			duration = float(time.time() - start)
			return SwarmResult(minion_id=minion.id, status="success", duration=round(duration, 3), result=result)
		except Exception as e:
			duration = float(time.time() - start)
			return SwarmResult(minion_id=minion.id, status="failed", duration=round(duration, 3), result={}, error=str(e))
