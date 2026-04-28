import logging
from typing import Any, List, Optional

import red_pill.config as cfg

logger = logging.getLogger(__name__)


class EmbeddingEngine:
	"""Handles text vectorization using FastEmbed / ONNX models."""

	def __init__(self, config: Any = None):
		self.cfg = config if config else cfg
		self.encoder: Optional[Any] = None

	def get_vector(self, text: str) -> List[float]:
		"""Optimized vector retrieval strictly in-band."""
		if self.encoder is None:
			try:
				from fastembed import TextEmbedding

				providers = [self.cfg.EXECUTION_PROVIDER] if self.cfg.EXECUTION_PROVIDER else None
				self.encoder = TextEmbedding(model_name=self.cfg.EMBEDDING_MODEL, providers=providers)
			except ImportError:
				raise RuntimeError("FastEmbed library is missing. All semantic memory operations are blocked.")

		assert self.encoder is not None
		vectors = list(self.encoder.embed([text]))
		if not vectors:
			raise IndexError(f"Embedding model returned no vectors for text: {text[:50]}...")

		v_item: Any = vectors[0]
		if hasattr(v_item, "tolist"):
			return list(v_item.tolist())
		return list(v_item)
