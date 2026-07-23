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
				import os
				from fastembed import TextEmbedding

				cache_path = getattr(self.cfg, "FASTEMBED_CACHE_PATH", None)
				local_only = getattr(self.cfg, "EMBEDDING_LOCAL_FILES_ONLY", True)
				providers = [self.cfg.EXECUTION_PROVIDER] if getattr(self.cfg, "EXECUTION_PROVIDER", None) else None

				if local_only and cache_path and os.path.exists(cache_path):
					try:
						self.encoder = TextEmbedding(
							model_name=self.cfg.EMBEDDING_MODEL,
							cache_dir=cache_path,
							local_files_only=True,
							providers=providers,
						)
					except Exception as e:
						logger.warning(f"[EMBEDDINGS] Offline load failed ({e}); falling back to standard load.")
						self.encoder = TextEmbedding(
							model_name=self.cfg.EMBEDDING_MODEL,
							cache_dir=cache_path,
							local_files_only=False,
							providers=providers,
						)
				else:
					self.encoder = TextEmbedding(
						model_name=self.cfg.EMBEDDING_MODEL,
						cache_dir=cache_path,
						local_files_only=local_only,
						providers=providers,
					)
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
