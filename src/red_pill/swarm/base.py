import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("red_pill.swarm")


from red_pill import config  # noqa: E402


class Minion(BaseModel):
	"""
	Base class for all transient, specialized agents in the Red Pill Swarm.
	Redesigned for Kernel integration (v5.0 Pioneer).
	"""

	id: str = Field(default_factory=lambda: str(uuid.uuid4()))
	name: str
	specialization: str
	telemetry_level: str = Field(default_factory=lambda: config.SWARM_TELEMETRY_DEFAULT)
	metadata: Dict[str, Any] = Field(default_factory=dict)

	model_config = ConfigDict(arbitrary_types_allowed=True)

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""Execute the assigned task. To be implemented by subclasses."""
		raise NotImplementedError("Minion subclasses must implement execute()")

	def log(self, message: str, level: int = logging.INFO):
		"""Standardized logging for minions."""
		logger.log(level, f"[{self.name}/{self.id[:4]}] {message}")


class SwarmResult(BaseModel):
	"""Standardized result wrapper for swarm operations."""

	minion_id: str
	status: str
	duration: float
	telemetry: Optional[Dict[str, Any]] = None
	result: Dict[str, Any]
	error: Optional[str] = None
