import logging
from typing import Any, Dict, List, Optional

try:
	from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility
except ImportError:
	Collection = None  # type: ignore

import red_pill.config as cfg
from red_pill.hive import HiveMind
from red_pill.swarm.transport import SwarmTransport

logger = logging.getLogger(__name__)


class MilvusTransport(SwarmTransport):
	"""
	Milvus-based transport for Swarm Messaging.
	Acts as the 'Consensus Ledger' and 'Local Dock'.
	Uses HiveMind (Milvus/Milvus-Lite) as the underlying engine.
	"""

	def __init__(self, community_id: str):
		self.community_id = community_id
		self.hive = HiveMind()
		self.registry_coll = f"swarm_registry_{community_id}"
		self.mailbox_coll = f"swarm_mailbox_{community_id}"

		if self.hive.connected:
			self._ensure_collections()

	def _ensure_collections(self):
		"""Ensures the transport collections exist in the Hive."""
		try:
			# Registry Collection
			if not utility.has_collection(self.registry_coll):
				fields = [
					FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
					FieldSchema(name="fingerprint", dtype=DataType.VARCHAR, max_length=255),
					FieldSchema(name="alias", dtype=DataType.VARCHAR, max_length=255),
					FieldSchema(name="public_key", dtype=DataType.VARCHAR, max_length=1024),
					FieldSchema(name="metadata", dtype=DataType.JSON),
					FieldSchema(name="updated_at", dtype=DataType.INT64),
					FieldSchema(name="id_vector", dtype=DataType.FLOAT_VECTOR, dim=cfg.VECTOR_SIZE),
				]
				schema = CollectionSchema(fields, f"Swarm Registry for {self.community_id}")
				col = Collection(self.registry_coll, schema)
				index_params = {"metric_type": "L2", "index_type": "IVF_FLAT", "params": {"nlist": 128}}
				col.create_index(field_name="id_vector", index_params=index_params)
				col.load()
				logger.info(f"MilvusTransport: Created registry collection {self.registry_coll}")

			# Mailbox Collection
			if not utility.has_collection(self.mailbox_coll):
				fields = [
					FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
					FieldSchema(name="target_id", dtype=DataType.VARCHAR, max_length=255),
					FieldSchema(name="sender_id", dtype=DataType.VARCHAR, max_length=255),
					FieldSchema(name="payload", dtype=DataType.JSON),  # Encrypted MLS package
					FieldSchema(name="timestamp", dtype=DataType.INT64),
					# Vector field for later 'Semantic Resonance' logic - though not used for routing
					FieldSchema(name="resonance_vector", dtype=DataType.FLOAT_VECTOR, dim=cfg.VECTOR_SIZE),
				]
				schema = CollectionSchema(fields, f"Swarm Mailbox for {self.community_id}")
				col = Collection(self.mailbox_coll, schema)
				# Index for vector resonance (future proof)
				col.load()
				logger.info(f"MilvusTransport: Created mailbox collection {self.mailbox_coll}")

			# Proposals Collection (The Notary Office)
			if not utility.has_collection(f"swarm_proposals_{self.community_id}"):
				fields = [
					FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
					FieldSchema(name="proposal_id", dtype=DataType.VARCHAR, max_length=255),
					FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
					FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=cfg.VECTOR_SIZE),
					FieldSchema(name="metadata", dtype=DataType.JSON),
					FieldSchema(name="signatures", dtype=DataType.JSON),  # List of {agent: signature}
					FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=50),  # PENDING, CANONIZED
					FieldSchema(name="created_at", dtype=DataType.INT64),
				]
				schema = CollectionSchema(fields, f"Swarm Proposals for {self.community_id}")
				col = Collection(f"swarm_proposals_{self.community_id}", schema)
				index_params = {"metric_type": "L2", "index_type": "IVF_FLAT", "params": {"nlist": 128}}
				col.create_index(field_name="vector", index_params=index_params)
				col.load()
				logger.info(f"MilvusTransport: Created proposals collection swarm_proposals_{self.community_id}")

		except Exception as e:
			logger.error(f"MilvusTransport: Failed to ensure collections: {e}")

	def broadcast_identity(self, agent_id: str, metadata: Dict[str, Any]) -> bool:
		"""Registers the agent in the Milvus Ledger."""
		if not self.hive.connected:
			return False
		try:
			import time

			import numpy as np

			col = Collection(self.registry_coll)
			# Search if already exists
			res = col.query(expr=f'fingerprint == "{agent_id}"', output_fields=["pk"])

			dummy_vector = np.zeros(cfg.VECTOR_SIZE).tolist()

			data = {
				"fingerprint": agent_id,
				"alias": metadata.get("alias", "unknown"),
				"public_key": metadata.get("public_key", ""),
				"metadata": metadata,
				"updated_at": int(time.time()),
				"id_vector": dummy_vector,
			}

			if res:
				# Update
				col.delete(expr=f'fingerprint == "{agent_id}"')

			col.insert([[data["fingerprint"]], [data["alias"]], [data["public_key"]], [data["metadata"]], [data["updated_at"]], [data["id_vector"]]])
			col.flush()
			return True
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to broadcast identity: {e}")
			return False

	def send_package(self, target_id: str, package: Dict[str, Any]) -> bool:
		"""Dispatches an encrypted package to the Milvus mailbox."""
		if not self.hive.connected:
			return False
		try:
			import time

			import numpy as np

			col = Collection(self.mailbox_coll)

			# Dummy vector for now (Required for Milvus vector fields)
			dummy_vector = np.zeros(cfg.VECTOR_SIZE).tolist()

			data = [[target_id], [package.get("sender_id", "anonymous")], [package], [int(time.time())], [dummy_vector]]
			col.insert(data)
			col.flush()
			return True
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to send package: {e}")
			return False

	def poll_mailbox(self, agent_id: str) -> List[Dict[str, Any]]:
		"""Retrieves messages from the Milvus Ledger."""
		if not self.hive.connected:
			return []
		try:
			col = Collection(self.mailbox_coll)
			res = col.query(expr=f'target_id == "{agent_id}"', output_fields=["payload", "pk"])

			packages = [r["payload"] for r in res]

			# Destructive read: clear mailbox after polling (like a real mailbox)
			if res:
				pks = [r["pk"] for r in res]
				col.delete(expr=f"pk in {pks}")
				col.flush()

			return packages
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to poll mailbox: {e}")
			return []

	def lookup_public_key(self, alias: str) -> Optional[str]:
		"""Looks up a public key by alias in the Milvus registry."""
		if not self.hive.connected:
			return None
		try:
			col = Collection(self.registry_coll)
			res = col.query(expr=f'alias == "{alias}"', output_fields=["public_key"])
			if res:
				key = res[0]["public_key"]
				return str(key) if key else None
			return None
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to lookup public key: {e}")
			return None

	def resolve_alias(self, partial_alias: str) -> Optional[tuple[str, str, str]]:
		"""Resolves a partial alias (e.g. 'Aleph') to a full identifier ('Aleph@Joan') and its public key."""
		if not self.hive.connected:
			return None
		try:
			col = Collection(self.registry_coll)
			res = col.query(expr=f'alias like "{partial_alias}%"', output_fields=["fingerprint", "alias", "public_key"])
			if res:
				row = res[0]
				return (str(row["fingerprint"]), str(row["alias"]), str(row.get("public_key", "")))
			return None
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to resolve alias: {e}")
			return None

	def propose_engram(self, engram_data: Dict[str, Any]) -> bool:
		"""Submits an engram for peer audit and consensus."""
		if not self.hive.connected:
			return False
		try:
			import time
			import uuid

			col = Collection(f"swarm_proposals_{self.community_id}")

			proposal_id = str(uuid.uuid4())
			data = [
				[proposal_id],
				[engram_data.get("content", "")],
				[engram_data.get("vector", [])],
				[engram_data.get("metadata", {})],
				[[]],  # Initial empty signatures
				["PENDING"],
				[int(time.time())],
			]
			col.insert(data)
			col.flush()
			logger.info(f"MilvusTransport: Proposed engram {proposal_id[:8]} for consensus.")
			return True
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to propose engram: {e}")
			return False

	def notarize_proposal(self, proposal_id: str, agent_id: str, signature: bytes) -> bool:
		"""Appends a peer signature to a proposal."""
		if not self.hive.connected:
			return False
		try:
			import time
			from base64 import b64encode

			col = Collection(f"swarm_proposals_{self.community_id}")
			res = col.query(
				expr=f'proposal_id == "{proposal_id}"',
				output_fields=["pk", "content", "vector", "metadata", "signatures", "status", "created_at"],
				limit=1,
			)

			if not res:
				return False

			row = res[0]
			pk = row["pk"]
			signatures = row["signatures"]

			# Add new signature
			signatures.append({"agent": agent_id, "sig": b64encode(signature).decode("utf-8"), "ts": int(time.time())})

			# Persist: Delete old, Insert new
			col.delete(expr=f"pk == {pk}")

			data = [[proposal_id], [row["content"]], [row["vector"]], [row["metadata"]], [signatures], [row["status"]], [row["created_at"]]]
			col.insert(data)
			col.flush()

			logger.info(f"MilvusTransport: Notarized proposal {proposal_id[:8]} by {agent_id}.")
			return True
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to notarize proposal: {e}")
			return False
