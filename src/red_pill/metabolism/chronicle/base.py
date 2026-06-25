"""
Base interfaces and classes for Chronicle Extractor Plugins.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class ChronicleExtractorPlugin(ABC):
	"""Abstract base class for all Chronicle extractor plugins."""

	@abstractmethod
	def extract(self) -> int:
		"""Extract conversation trajectories from the respective IDE/environment.

		Saves the extracted conversations as JSON files in the staging directory
		so the metabolism sleep cycle can ingest them.

		Returns:
			int: Number of new or updated trajectories snatched/staged.
		"""
		pass
