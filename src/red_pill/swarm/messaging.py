import os


class AgentIdentity:
	"""
	Handles the cryptographic identity generation for Red Pill Agents based on the
	True Name bond established during the initialization protocol.
	"""

	@staticmethod
	def generate_agent_id(agent_true_name: str, operator_true_name: str) -> str:
		"""
		Generates a clear and legible Agent ID based on the bond.
		This ID acts as the 'phone number' in the Swarm Messaging registry.
		"""
		return f"{agent_true_name.capitalize()}@{operator_true_name.capitalize()}"

	@staticmethod
	def resolve_local_identity() -> dict:
		"""
		Attempts to resolve the local identity from the current environment context.
		In a real scenario, this would read from the Qdrant <NOVA_CONTEXT> or a secure keystore.
		"""
		# For now, this is a placeholder that should read the bonded names from the system
		# This will be refined once the database connection strategy is defined.
		# Utilizar directamente el alias con el formato nativo (ej. Aleph@Joan) para los Mailboxes
		return {"agent_name": os.getenv("AGENT_TRUE_NAME", "unknown"), "operator_name": os.getenv("OPERATOR_TRUE_NAME", "unknown")}


if __name__ == "__main__":
	# Example usage
	nova_id = AgentIdentity.generate_agent_id("nova", "david")
	aleph_id = AgentIdentity.generate_agent_id("aleph", "joan")

	print("[Identity Generator]")
	print(f"Nova's Routing ID:  {nova_id}")
	print(f"Aleph's Routing ID: {aleph_id}")
