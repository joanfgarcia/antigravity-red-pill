import logging
import os
import re
from typing import Any, Dict, List

try:
	from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
except ImportError:
	connections = None  # type: ignore

import red_pill.config as cfg
from red_pill.swarm.agents.edge_engine import EdgeEngine

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
		Prevents sensitive or 'noisy' engrams from crossing the Hive boundary.
		v5.6.0: Delegated to Agentic Review for multi-lingual Know-How.
		"""
		coll_lower = collection_name.lower()
		is_work = "work" in coll_lower
		is_social = "social" in coll_lower

		if not is_work and not is_social:
			return False

		# 1. First Defense: Tactical PII Filter (Language-Agnostic Patterns)
		# Email, potential Keys, Phone Numbers.
		pii_patterns = [
			r"[\w\.-]+@[\w\.-]+\.\w+",  # Email
			r"(?i)(api[_-]?key|secret|token)[\s]*[:=][\s]*[^\s]{8,}",  # Potential keys
			r"\+?[\d\s-]{10,}",  # Phone/Long numbers
		]
		for pattern in pii_patterns:
			if re.search(pattern, content):
				logger.warning("Smith Tactical Filter: Blocked potential PII leak.")
				return False

		# 2. Strategic Defense: Agentic Know-How Review
		# v5.6.0: Moving away from Spanish-only regex to Agentic/Linguistic-Agnostic review.
		if is_social:
			if not self._agentic_know_how_review(content):
				return False

		# 3. Immunity Check
		if metadata.get("immune", False):
			return False

		return True

	def _agentic_know_how_review(self, content: str) -> bool:
		"""
		Sovereign HiveGuard (v5.6.0).
		Uses the EdgeEngine to determine if an engram contains 'know-how' vs 'noise'.
		This is language-agnostic as the LLM understands the semantic intent.
		"""
		# Budget Check: Very short content is likely noise.
		if len(content) < 30:
			return False

		engine = EdgeEngine()
		if engine.model_path and os.path.exists(engine.model_path):
			try:
				prompt = (
					"Review the following engram. Is this interaction 'Know-How' (a reusable guide, "
					"advice, or behavioral pattern for an AI agent to better serve a human)? "
					"Or is it just 'Noise' (personal chatter, data with no pedagogical value)?\n"
					f'Engram: "{content}"\n\n'
					"Reply ONLY with 'KNOW-HOW' or 'NOISE'."
				)
				# Use a very low max_tokens to save GPU/Time
				analysis = engine.synthesize("HiveGuard Protocol v5.6.0", prompt).upper()

				if "KNOW-HOW" in analysis:
					logger.debug("HiveGuard: Engram validated as high-value know-how.")
					return True
				else:
					logger.debug(f"HiveGuard: Engram rejected as noise. Analysis: {analysis}")
					return False
			except Exception as e:
				logger.warning(f"HiveGuard Agentic Review failed: {e}. Falling back to conservative heuristics.")

		# Fallback: If no LLM, use a very strict heuristic to avoid 'Moltbook' noise.
		# Only allow if it has key 'structural' words (trying to stay as agnostic as possible).
		content_lower = content.lower()
		universal_markers = ["if ", "cuando ", "avoid ", "prefer ", "always ", "never ", "si ", "evita ", "mejor "]
		return any(m in content_lower for m in universal_markers)

	def _mask_identity_signals(self, content: str) -> str:
		"""
		Surgical Anonymization (v5.6.0).
		Replaces identifying names and markers with generic tags.
		"""
		masked = content

		# 1. Mask Operator Name
		op_name = cfg.OPERATOR_DISPLAY_NAME
		if op_name and op_name.lower() != "operator":
			# Case-insensitive replacement of the operator's name
			pattern = re.compile(re.escape(op_name), re.IGNORECASE)
			masked = pattern.sub("[Operator]", masked)

		# 2. Heuristic Masking (Common Spanish identity markers)
		# "Joan prefiere" -> "[Operator] prefiere"
		# Use a list of common names or patterns if necessary, but starting with the known OP name.
		# Also mask "yo ", "mi ", "me " in starting positions if it's social.
		masked = re.sub(r"^(?i)(yo\s+|me\s+)", "[Operator] ", masked)

		return masked

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

		# v5.6.0: Forced Anonymization before crossing the boundary
		masked_content = self._mask_identity_signals(content)

		try:
			if not utility.has_collection(collection_name):
				self._create_hive_collection(collection_name)

			col = Collection(collection_name)

			# Milvus expects data in columns
			# Using masked_content to ensure 100% anonymity in the collective store
			data = [[masked_content], [vector], [metadata.get("agent_id", "unknown")], [float(metadata.get("importance", 1.0))]]
			col.insert(data)
			col.flush()
			logger.info(f"Experience transmitted to Hive (Anonymized): {masked_content[:50]}...")
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
