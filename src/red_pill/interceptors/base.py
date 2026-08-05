import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseInterceptorPlugin(ABC):
	"""Base class for all Bünker interceptor plugins."""

	@property
	@abstractmethod
	def name(self) -> str:
		pass

	@property
	@abstractmethod
	def timeout(self) -> float:
		"""Maximum allowed execution time in seconds."""
		pass

	@property
	def is_enabled(self) -> bool:
		"""Override to conditionally disable the plugin (e.g. based on config)."""
		return True

	@abstractmethod
	async def execute(self, prompt: str) -> str:
		"""
		Execute the plugin logic.
		Should return a passive context block to append, or empty string.
		If it returns a special '<LOCAL_RESPONSE_READY>' block, the pipeline short-circuits.
		"""
		pass

	def paint_chroma(self, color: str) -> None:
		"""Record a chroma referenced in this plugin's output. The Mood Orchestrator
		aggregates painted chromas across subplugins and renders ONE legend at the
		end of the pipeline (CHROMA KEY) — plugins never explain colors inline."""
		if color:
			if not hasattr(self, "_painted_chromas"):
				self._painted_chromas: set[str] = set()
			self._painted_chromas.add(color.lower())

	@property
	def painted_chromas(self) -> set:
		return getattr(self, "_painted_chromas", set())
