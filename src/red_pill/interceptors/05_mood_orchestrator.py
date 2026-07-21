"""
Mood Orchestrator — Ferrari Plugin 05 (Consolidated)
=====================================================
Delegator that encapsulates the mood pipeline (cognitive router, tone adapter,
mood analytics, emotive recall, proactive signal) into a single plugin entry point.

Each subplugin runs sequentially with independent error isolation.
Failures emit a pain signal but do not stop the pipeline.

Enable/Disable: MOOD_ORCHESTRATOR_ENABLED=true in .env
"""

import asyncio
import importlib
import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)

# Subplugin module names (in execution order)
_SUBPLUGINS = [
	"red_pill.interceptors.05_cognitive_router",
	"red_pill.interceptors.06_tone_adapter",
	"red_pill.interceptors.07_mood_analytics",
	"red_pill.interceptors.08_emotive_recall",
	"red_pill.interceptors.09_proactive_signal",
]


def _load_subplugin(module_path: str):
	"""Load and return the first BaseInterceptorPlugin subclass from a module."""
	try:
		module = importlib.import_module(module_path)
		for attr_name in dir(module):
			attr = getattr(module, attr_name)
			if (
				isinstance(attr, type)
				and issubclass(attr, BaseInterceptorPlugin)
				and attr is not BaseInterceptorPlugin
			):
				return attr()
	except Exception as e:
		logger.error(f"Mood Orchestrator: failed to load subplugin {module_path}: {e}")
	return None


def _emit_pain_signal(source: str, error: str):
	"""Emit a pain signal to Bünker when a subplugin fails."""
	try:
		from red_pill.memory import MemoryManager

		mgr = MemoryManager()
		mgr.inject_signal(
			f"mood_subplugin_failure_{source}",
			intensity=4.0,
			signal_type="pain",
			source=f"MOOD_ORCHESTRATOR:{source}",
		)
	except Exception as e:
		logger.debug(f"Mood Orchestrator: failed to emit pain signal: {e}")


class MoodOrchestratorPlugin(BaseInterceptorPlugin):
	"""
	Consolidated mood orchestrator. Delegates to subplugins sequentially
	with independent error isolation per subplugin.
	"""

	@property
	def name(self) -> str:
		return "Mood Orchestrator (Ferrari 05-09)"

	@property
	def timeout(self) -> float:
		return 8.0

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		subplugins = []
		for module_path in _SUBPLUGINS:
			sp = _load_subplugin(module_path)
			if sp and sp.is_enabled:
				subplugins.append(sp)

		if not subplugins:
			return ""

		results = []
		for sp in subplugins:
			try:
				output = await asyncio.wait_for(sp.execute(prompt), timeout=sp.timeout)
				if output and output.strip():
					results.append(output.strip())
			except asyncio.TimeoutError:
				logger.warning(f"Mood Orchestrator: subplugin '{sp.name}' timed out after {sp.timeout}s")
				_emit_pain_signal(sp.name, "timeout")
			except Exception as e:
				logger.error(f"Mood Orchestrator: subplugin '{sp.name}' crashed: {e}")
				_emit_pain_signal(sp.name, str(e))

		# ── CHROMA KEY (dominant mood color) ──
		try:
			from red_pill.utils.tone_analyzer import get_current_sync_state

			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray")
			results.append(f"chroma: {color}")
		except Exception:
			pass

		return "\n".join(results) if results else ""
