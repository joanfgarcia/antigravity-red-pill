import logging
import re
from typing import Any, Dict, List

try:
	from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
except ImportError:
	connections = None  # type: ignore

import red_pill.config as cfg

logger = logging.getLogger(__name__)


class HiveMind:
	"""
	The Hive Mind (Milvus).
	Shared collective intelligence for Red Pill units.
	Qdrant is the individual brain; Milvus is the network of experience.
	"""

	def __init__(self):
		self.enabled = cfg.MILVUS_ENABLED
		self.connected = False
		if self.enabled and connections:
			try:
				# SEC-F03: Enforce TLS for remote connections
				is_local = cfg.MILVUS_HOST in ["localhost", "127.0.0.1", "::1"]
				secure_conn = cfg.MILVUS_SECURE
				if not is_local and not secure_conn:
					logger.error("[SEC-F03] HiveMind connection blocked: TLS required for remote hosts.")
					self.connected = False
					return

				connections.connect(
					alias="default",
					host=cfg.MILVUS_HOST,
					port=cfg.MILVUS_PORT,
					user=cfg.MILVUS_USER,
					password=cfg.MILVUS_PASSWORD,
					secure=secure_conn,
					db_name=cfg.MILVUS_DB,
				)

				self.connected = True

				logger.info("Hive Mind (Milvus) connected successfully.")
			except Exception as e:
				logger.error(f"Failed to connect to Hive Mind: {e}")
				self.connected = False

	def _passes_smith_filter(self, collection_name: str, content: str, metadata: Dict[str, Any]) -> bool:
		"""
		Forensic PII and Identity filter (SEC-F03).
		Prevents sensitive engrams from crossing the Hive boundary.
		"""
		# 1. Identity Substrate Protection
		# Only 'work_memories' are allowed to cross the boundary.
		if "work" not in collection_name.lower():
			return False

		# 2. Immunity Check
		# Genesis directives and operator-specific immune engrams are NEVER broadcast.
		if metadata.get("immune", False):
			return False

		# 3. PII Pre-Filter (Regex)
		# Patterns: Email, potential Keys, and Phone Numbers.
		pii_patterns = [
			r"[\w\.-]+@[\w\.-]+\.\w+",  # Email
			r"(?i)(api[_-]?key|secret|token)[\s]*[:=][\s]*[^\s]{8,}",  # Potential keys
			r"\+?[\d\s-]{10,}",  # Phone/Long numbers
		]
		for pattern in pii_patterns:
			if re.search(pattern, content):
				logger.warning("Smith Pre-Filter: Blocked PII pattern in experience transmission.")
				return False

		return True

	def transmit_experience(self, collection_name: str, content: str, vector: List[float], metadata: Dict[str, Any]):
		"""
		Broadcasts an engram to the collective.
		Every architectural breakthrough or finding is shared here.
		"""
		if not self.connected:
			return

		# TST-001: Integrated Smith Pre-Filter (Forensic Shield)
		if not self._passes_smith_filter(collection_name, content, metadata):
			return

		try:
			if not utility.has_collection(collection_name):
				self._create_hive_collection(collection_name)

			col = Collection(collection_name)

			# Milvus expects data in columns
			data = [[content], [vector], [metadata.get("agent_id", "unknown")], [float(metadata.get("importance", 1.0))]]
			col.insert(data)
			col.flush()
			logger.info(f"Experience transmitted to Hive: {content[:50]}...")
		except Exception as e:
			logger.error(f"Hyper-transmission failure: {e}")

	def _create_hive_collection(self, name: str):
		"""Initializes a new sector in the collective memory."""
		fields = [
			FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
			FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
			FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=cfg.VECTOR_SIZE),
			FieldSchema(name="source_agent", dtype=DataType.VARCHAR, max_length=255),
			FieldSchema(name="importance", dtype=DataType.FLOAT),
		]
		schema = CollectionSchema(fields, "Hive Mind Collective Sector")
		col = Collection(name, schema)

		# Create index for search
		index_params = {"metric_type": "L2", "index_type": "IVF_FLAT", "params": {"nlist": 128}}
		col.create_index(field_name="vector", index_params=index_params)
		col.load()

	def sync_from_hive(self, query_vector: List[float], collection_name: str, limit: int = 5) -> List[Dict[str, Any]]:
		"""
		Inherit the total sum of siblings' experience.
		Like a wildebeest walking minutes after birth.
		"""
		if not self.connected or not utility.has_collection(collection_name):
			return []

		try:
			col = Collection(collection_name)
			search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
			results = col.search(
				data=[query_vector], anns_field="vector", param=search_params, limit=limit, output_fields=["content", "source_agent", "importance"]
			)

			experiences = []
			for hits in results:
				for hit in hits:
					experiences.append(
						{
							"content": hit.entity.get("content"),
							"source_agent": hit.entity.get("source_agent"),
							"importance": hit.entity.get("importance"),
							"distance": hit.distance,
						}
					)
			return experiences
		except Exception as e:
			logger.error(f"Sync from Hive failed: {e}")
			return []
