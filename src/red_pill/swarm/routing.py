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
		Determines the best provider based on task requirements, validating capabilities
		and applying graceful degradation to cheaper models if token exhaustion occurs.
		"""
		required_capability = task_metadata.get("required_capability", "general")
		strict_validation = task_metadata.get("strict_validation", False)

		# 0. Emergency Cloud Override
		import red_pill.config as cfg
		if cfg.get_config().EMERGENCY_CLOUD_OVERRIDE:
			providers_to_try = ["openai", "flash"]
		else:
			local_only = task_metadata.get("local_only", False)
			tier = task_metadata.get("model_tier", "standard")

			providers_to_try = []

			# 1. Force local if requested or if tier is ternary
			if local_only or tier == "ternary":
				providers_to_try.append("bitnet")
			# 2. Try SIP for local-first non-ternary
			elif tier == "local_first":
				providers_to_try.extend(["sip", "bitnet"])
			# 3. Graceful degradation: If tokens run low, use 'cheap' tier (Flash/Mini)
			elif tier == "cheap":
				providers_to_try.extend(["flash", "openai_mini", "openai"])
			else:
				# Default standard
				default_key = ProviderRegistry._default_inference_key
				if default_key:
					providers_to_try.append(default_key)
				providers_to_try.extend(["openai", "flash", "sip"])

		available_providers = ProviderRegistry.list_inference_providers()
		if not available_providers:
			# Critical Blindness: Nothing is available. Hardware warnings become fatal here.
			raise RuntimeError("CRITICAL BLINDNESS: No inference providers available in registry. Hardware/Token failure total.")

		for p_key in providers_to_try:
			if p_key in available_providers:
				provider = ProviderRegistry.get_inference_provider(p_key)
				# Run the Capability Exam
				if provider.validate_task_capability(required_capability):
					return provider
				elif strict_validation:
					raise RuntimeError(f"Strict validation failed: Provider '{p_key}' has not passed the exam for '{required_capability}'.")

		raise RuntimeError(f"No registered inference provider passed the capability exam for task: {required_capability}")
