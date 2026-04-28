from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SwarmTransport(ABC):
	"""
	Abstract Base Class for Swarm Transport Plugins.
	Ensures that messaging is agnostic to the underlying database or service.
	"""

	@abstractmethod
	def broadcast_identity(self, agent_id: str, metadata: Dict[str, Any]) -> bool:
		"""Registers or updates the agent's identity in the community registry."""
		pass

	@abstractmethod
	def send_package(self, target_id: str, package: Dict[str, Any]) -> bool:
		"""Dispatches an encrypted package to a specific target's mailbox."""
		pass

	@abstractmethod
	def poll_mailbox(self, agent_id: str) -> List[Dict[str, Any]]:
		"""Retrieves incoming packages for the agent."""
		pass

	@abstractmethod
	def lookup_public_key(self, alias: str) -> Optional[str]:
		"""Finds the public key (Base64) for a given alias in the registry."""
		pass

	@abstractmethod
	def resolve_alias(self, partial_alias: str) -> Optional[tuple[str, str, str, str]]:
		"""Resolves a partial alias (e.g. 'Aleph') to a full identifier ('Aleph@Joan') and its public key."""
		pass
