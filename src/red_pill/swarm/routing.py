import logging
from typing import Any, Dict

from red_pill.core.providers import BaseInferenceProvider, ProviderRegistry

logger = logging.getLogger("red_pill.swarm.routing")


class InferenceRouter:
	"""
	Routes inference tasks to the appropriate provider (Local vs Remote).
	"""

	@staticmethod
	def get_provider_for_task(task_metadata: Dict[str, Any]) -> BaseInferenceProvider:
		"""
		Determines the best provider based on task requirements.
		- local_only: Force BitNet
		- model_tier: 'ternary' -> BitNet, 'enterprise' -> OpenAI
		"""
		local_only = task_metadata.get("local_only", False)
		tier = task_metadata.get("model_tier", "standard")

		# 1. Force local if requested or if tier is ternary
		if local_only or tier == "ternary":
			try:
				return ProviderRegistry.get_inference_provider("bitnet")
			except RuntimeError:
				logger.warning("BitNet provider requested but not registered. Falling back to default.")

		# 2. Try SIP for local-first non-ternary (e.g. Samantha)
		if tier == "local_first":
			try:
				return ProviderRegistry.get_inference_provider("sip")
			except RuntimeError:
				pass

		# 3. Default to the primary registered provider (usually OpenAI)
		try:
			return ProviderRegistry.get_inference_provider()
		except RuntimeError:
			# Final fallback to OpenAI key-based if not registered (defensive)
			raise RuntimeError("No inference providers available in registry.")
