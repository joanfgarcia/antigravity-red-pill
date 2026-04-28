import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)


class CircuitBreakerPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "SLM Circuit Breaker (Short-Circuit)"

	@property
	def timeout(self) -> float:
		return 2.5  # Allow 2.5 seconds for local LLM evaluation

	@property
	def is_enabled(self) -> bool:
		# Apagado por defecto por orden del Operador ("ni en pintura") y además ligado a cfg
		return getattr(cfg, "INTERCEPTOR_ENABLED", False) and getattr(cfg, "INTERCEPTOR_CIRCUIT_BREAKER_ENABLED", False)

	async def execute(self, prompt: str) -> str:
		try:
			import asyncio

			def _evaluate():
				from red_pill.swarm.agents.edge_engine import EdgeEngine

				engine = EdgeEngine()
				engine._ensure_loaded()

				if not engine.llm:
					return ""

				eval_sys = (
					"You are an internal routing Gatekeeper. Evaluate the user's prompt strictly.\n"
					"If you have enough hard factual data to answer the prompt conclusively directly from memory, you MUST prefix your answer with the EXACT string `[VALID]`.\n"
					"If you don't have enough data, or the prompt is narrative, conversational, or philosophical, do NOT use the prefix. Output ONLY: `INSUFFICIENT_CONTEXT`."
				)
				formatted_prompt = f"<|im_start|>system\n{eval_sys}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

				try:
					output = engine.llm(
						formatted_prompt,
						max_tokens=64,
						stop=["<|im_end|>", "<|im_start|>", "</s>", "<|endoftext|>"],
						temperature=0.0,
					)
					if isinstance(output, dict):
						return str(output["choices"][0]["text"]).strip()
				except Exception as e:
					logger.error(f"Circuit Breaker SLM failed: {e}")
				return "INSUFFICIENT_CONTEXT"

			local_answer = await asyncio.to_thread(_evaluate)

			if "[VALID]" in local_answer:
				clean_answer = local_answer.replace("[VALID]", "").strip()
				if clean_answer:
					return f"<LOCAL_RESPONSE_READY>\n{clean_answer}\n</LOCAL_RESPONSE_READY>"

			return ""
		except Exception as e:
			logger.error(f"Circuit Breaker crashed: {e}")
			return ""
