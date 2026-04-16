import asyncio
import json
import logging
import os
import time
import uuid
from typing import List, Union

from red_pill.config import FLOW_REGISTRY_PATH, SIP_SOCKET_PATH
from red_pill.core.inbox import MinionInbox
from red_pill.core.model_registry import ModelRegistry
from red_pill.core.providers import BitNetInferenceProvider, OpenAIInferenceProvider, ProviderRegistry, SipInferenceProvider
from red_pill.swarm.base import Minion, SwarmResult
from red_pill.swarm.factory import MinionFactory
from red_pill.swarm.flow_engine import FlowEngine
from red_pill.swarm.routing import InferenceRouter
from red_pill.utils.observer import notify_user
from red_pill.utils.specs_adapter import SpecsAdapter

logger = logging.getLogger(__name__)


class SwarmScheduler:
	"""
	Model-Aware Batch Scheduler.
	Implements Context Affinity, Hardware Routing (VRAM NGL check) and Anti-Starvation (Aging TTL).
	"""

	def __init__(self, orchestrator):
		self.orchestrator = orchestrator
		self.queue = []
		self.hot_profile = None
		self.is_processing = False
		self.lock = asyncio.Lock()
		self.MAX_WAIT_TTL = 30.0  # seconds before anti-starvation kicks in

	async def enqueue(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		future = asyncio.get_running_loop().create_future()
		item = {"minion": minion, "task": task, "kwargs": kwargs, "future": future, "enqueue_time": time.time()}
		async with self.lock:
			self.queue.append(item)

		# Trigger processor asynchronously
		asyncio.create_task(self._process_queue())
		return await future

	async def _process_queue(self):
		if self.is_processing:
			return

		async with self.lock:
			if self.is_processing or not self.queue:
				return
			self.is_processing = True

		try:
			while True:
				async with self.lock:
					if not self.queue:
						break

					now = time.time()
					# 1. Anti-Starvation Check (Aging)
					starving_tasks = [i for i in self.queue if now - i["enqueue_time"] > self.MAX_WAIT_TTL]

					if starving_tasks:
						next_item = starving_tasks[0]
						logger.info(f"Anti-Starvation context switch forced for {next_item['minion'].id}. TTL > {self.MAX_WAIT_TTL}s")
					else:
						# 2. Context Affinity Check
						hot_tasks = [i for i in self.queue if getattr(i["minion"], "model_profile", None) == self.hot_profile]
						if hot_tasks:
							next_item = hot_tasks[0]
						else:
							# Pick the oldest if no affinity matches
							next_item = self.queue[0]

					self.queue.remove(next_item)
					self.hot_profile = getattr(next_item["minion"], "model_profile", None)

				await self._execute_item(next_item)
		finally:
			self.is_processing = False

	async def _execute_item(self, item):
		minion, task, base_kwargs = item["minion"], item["task"], item["kwargs"]

		# Override Profile logic
		profile_data = ModelRegistry.get_profile(self.hot_profile) if self.hot_profile else {}
		exec_kwargs = base_kwargs.copy()
		exec_kwargs.update(profile_data)

		# Hardware VRAM Routing
		telemetry_provider = ProviderRegistry.get_telemetry_provider()
		try:
			stats = telemetry_provider.get_stats()
			vram_free = stats.get("vram_free_mb", 0)
			exec_kwargs["ngl"] = 99 if vram_free > 3000 else 0
		except Exception:
			exec_kwargs["ngl"] = 0

		try:
			result = await self.orchestrator._run_minion(minion, task, **exec_kwargs)
			if not item["future"].done():
				item["future"].set_result(result)
		except Exception as e:
			if not item["future"].done():
				item["future"].set_exception(e)


class GruOrchestrator:
	"""
	The Sovereign Orchestrator (Gru).
	Manages the deployment and collection of specialized Minions.
	Integrated with Enterprise Mode Providers and the Inference Router.
	"""

	def __init__(self):
		self.active_minions: List[Minion] = []
		self.workspace_root = os.getcwd()
		self.specs = SpecsAdapter(self.workspace_root)
		self.inbox = MinionInbox()
		self.flow_engine = FlowEngine(FLOW_REGISTRY_PATH)
		self.scheduler = SwarmScheduler(self)
		self._setup_providers()

	def _setup_providers(self):
		"""Initialize and register default inference providers (Enterprise Mode)."""
		# 1. OpenAI Provider
		api_key = os.getenv("OPENAI_API_KEY")
		if api_key:
			ProviderRegistry.register_inference_provider("openai", OpenAIInferenceProvider(api_key=api_key), default=True)

		# 2. SIP Provider (Local Socket)
		if os.path.exists(SIP_SOCKET_PATH):
			ProviderRegistry.register_inference_provider("sip", SipInferenceProvider(socket_path=SIP_SOCKET_PATH))

		# 3. BitNet Provider (Direct Binary)
		# Path from experimental investigation
		bitnet_bin = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/bin/llama-cli")
		bitnet_model = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf")
		if os.path.exists(bitnet_bin) and os.path.exists(bitnet_model):
			grammar_path = os.path.join(os.path.dirname(FLOW_REGISTRY_PATH), "../inference/bitnet/json.gbnf")
			ProviderRegistry.register_inference_provider(
				"bitnet", BitNetInferenceProvider(runner_path=bitnet_bin, model_path=bitnet_model, grammar_path=grammar_path)
			)

	def is_local_ready(self) -> bool:
		"""Check if local SLM infrastructure is available."""
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

		# 2. Enrichment logic (removed specs dependency to simplify for Enterprise audit)
		enriched_task = task

		# 3. Deploy Minions via the Scheduler
		logger.info(f"Deploying swarm to execute: {task[:50]}...")
		tasks_parallel = [self.scheduler.enqueue(m, enriched_task, **kwargs) for m in resolved_minions]
		results = await asyncio.gather(*tasks_parallel)

		# 4. SAS: Sovereign Alert System integration (Selective Tracing)
		if trace:
			self._trigger_sas(task, results)

		return results

	def _trigger_sas(self, task: str, results: List[SwarmResult]) -> None:
		"""Record memory and notify user of swarm completion with telemetry."""
		success_count = len([r for r in results if r.status == "success"])
		task_preview = task[:100] if isinstance(task, str) else "task"

		telemetry_summary = ""
		for r in results:
			if r.telemetry:
				delta = r.telemetry.get("vram_delta", "N/A")
				vram_info = f" | VRAM: {delta}" if delta != "N/A" else ""
				telemetry_summary += f"\n- {r.minion_id[:8]}: {r.duration}s{vram_info}"

		message = f"Swarm Task Complete: {task_preview}. {success_count}/{len(results)} minions succeeded.{telemetry_summary}"
		notify_user(title="Sovereign Swarm", message=message, sound=False, category="swarm")

		# Memory Signal (Agent)
		try:
			event_id = str(uuid.uuid4())[:8]
			metadata = {
				"type": "swarm_event",
				"timestamp": time.time(),
				"results_summary": [{"minion": r.minion_id, "status": r.status, "duration": r.duration} for r in results],
			}
			full_content = f"{message}\n\nMetadata: {json.dumps(metadata, indent=2)}"
			self.inbox.drop_report(
				event_id=event_id, source="GruOrchestrator", status="success" if success_count > 0 else "failed", content=full_content
			)
		except Exception as e:
			logger.error(f"SAS Inbox Hook failed: {e}")

	async def run_autonomous_flow(self, flow_id: str, **kwargs) -> List[SwarmResult]:
		"""Executes a predefined flow template."""
		flow = self.flow_engine.get_flow(flow_id, self.workspace_root)
		if not flow:
			raise ValueError(f"Flow '{flow_id}' not found.")

		logger.info(f"🚀 INICIANDO FLUJO: {flow.get('name', flow_id)}")

		overall_results = []
		for step in flow.get("steps", []):
			minion_id = step.get("minion")
			on_fail = step.get("on_fail", "warn")

			minion = MinionFactory.create(minion_id)
			if not minion:
				continue

			results = await self.deploy_swarm(task=f"Flow Step: {minion_id}", minions=[minion], **kwargs)
			overall_results.extend(results)

			if any(r.status == "failed" for r in results) and on_fail in ("stop", "abort"):
				break

		return overall_results

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		telemetry_provider = ProviderRegistry.get_telemetry_provider()
		level = minion.telemetry_level
		start_time = time.time()

		# 1. Select Inference Provider via Router
		# We inject the chosen provider into kwargs so the minion can use it
		try:
			inference_provider = InferenceRouter.get_provider_for_task(kwargs)
			kwargs["inference_provider"] = inference_provider
		except Exception as e:
			logger.warning(f"Failed to resolve inference provider: {e}")

		# Pre-task telemetry
		pre_stats = None
		if level != "NONE":
			pre_stats = telemetry_provider.get_stats()

		try:
			result = await minion.execute(task, **kwargs)
			duration = float(time.time() - start_time)

			telemetry = None
			if level != "NONE" and pre_stats:
				post_stats = telemetry_provider.get_stats()
				impact = telemetry_provider.compute_delta(pre_stats, post_stats)
				telemetry = {"pre": pre_stats, "post": post_stats, "impact": impact, "vram_delta": f"{impact.get('vram_delta_mb', 0)} MB"}

			return SwarmResult(minion_id=minion.id, status="success", duration=round(duration, 3), telemetry=telemetry, result=result)
		except Exception as e:
			duration = float(time.time() - start_time)
			telemetry_err = None
			if level != "NONE" and pre_stats:
				telemetry_err = {"pre": pre_stats, "error_context": True}
			return SwarmResult(minion_id=minion.id, status="failed", duration=round(duration, 3), telemetry=telemetry_err, result={}, error=str(e))
