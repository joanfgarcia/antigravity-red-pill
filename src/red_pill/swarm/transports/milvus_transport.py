import logging
from typing import Any, Dict, List, Optional

try:
	from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility
except ImportError:
	Collection = None # type: ignore

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
					FieldSchema(name="payload", dtype=DataType.JSON), # Encrypted MLS package
					FieldSchema(name="timestamp", dtype=DataType.INT64),
					# Vector field for later 'Semantic Resonance' logic - though not used for routing
					FieldSchema(name="resonance_vector", dtype=DataType.FLOAT_VECTOR, dim=cfg.VECTOR_SIZE),
				]
				schema = CollectionSchema(fields, f"Swarm Mailbox for {self.community_id}")
				col = Collection(self.mailbox_coll, schema)
				# Index for vector resonance (future proof)
				index_params = {"metric_type": "L2", "index_type": "IVF_FLAT", "params": {"nlist": 128}}
				col.create_index(field_name="resonance_vector", index_params=index_params)
				col.load()
				logger.info(f"MilvusTransport: Created mailbox collection {self.mailbox_coll}")

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
				"id_vector": dummy_vector
			}
			
			if res:
				# Update
				col.delete(expr=f'fingerprint == "{agent_id}"')
			
			col.insert([
				[data["fingerprint"]],
				[data["alias"]],
				[data["public_key"]],
				[data["metadata"]],
				[data["updated_at"]],
				[data["id_vector"]]
			])
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
			
			data = [
				[target_id],
				[package.get("sender_id", "anonymous")],
				[package],
				[int(time.time())],
				[dummy_vector]
			]
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
				return res[0]["public_key"]
			return None
		except Exception as e:
			logger.error(f"MilvusTransport: Failed to lookup public key: {e}")
			return None
