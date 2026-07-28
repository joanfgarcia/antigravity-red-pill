import logging
import time
from functools import wraps
from typing import Any, Callable, Generator, List, Optional, TypeVar

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException

import red_pill.config as cfg
from red_pill.events import CollectionCreatedEvent, get_event_bus

logger = logging.getLogger(__name__)

_RETRY_MAX = 3
_RETRY_BACKOFF = 0.5  # seconds, doubles each attempt


def _mask_pii_exception(e: Exception) -> str:
	"""Truncates exception strings to prevent payload PII leaks."""
	msg = str(e)
	return msg if len(msg) < 150 else msg[:150] + "... [TRUNCATED]"


F = TypeVar("F", bound=Callable[..., Any])


def retry_on_qdrant_error(func: F) -> F:
	"""Retry transient Qdrant failures with exponential backoff.

	Only ResponseHandlingException is retried: qdrant-client wraps httpx transport
	errors (connection reset, timeout, disconnect) in it. Any other exception —
	including UnexpectedResponse for HTTP-level errors — propagates immediately.
	The last attempt re-raises, so the wrapper never returns None on exhaustion.
	"""

	@wraps(func)
	def wrapper(*args: Any, **kwargs: Any) -> Any:
		for attempt in range(_RETRY_MAX):
			try:
				return func(*args, **kwargs)
			except ResponseHandlingException as e:
				if attempt == _RETRY_MAX - 1:
					logger.error(f"Qdrant operation '{func.__name__}' failed after {_RETRY_MAX} attempts: {_mask_pii_exception(e)}")
					raise
				wait = _RETRY_BACKOFF * (2**attempt)
				logger.warning(
					f"Qdrant transient error in '{func.__name__}' (attempt {attempt + 1}/{_RETRY_MAX}): {_mask_pii_exception(e)}. Retrying in {wait}s..."
				)
				time.sleep(wait)
		raise AssertionError("unreachable: retry loop always returns or raises")

	return wrapper  # type: ignore[return-value]


class StorageEngine:
	"""Core interface for Qdrant persistence. Encapsulates all raw client calls."""

	def __init__(self, url: str = cfg.QDRANT_URL, config: Any = None):
		self.cfg = config if config else cfg

		# ACT-P1-02: Network Security Kill-Switch
		self.client: QdrantClient
		if url == ":memory:":
			self.client = QdrantClient(location=":memory:")
		else:
			is_local = any(local in url for local in ["localhost", "127.0.0.1", "0.0.0.0"])
			if not is_local and not self.cfg.QDRANT_API_KEY:
				logger.critical(f"SEC-CR-02: Qdrant at '{url}' is exposed to the network without an API key.")
				raise RuntimeError("Aborting execution to protect Bünker sovereignty. Set QDRANT_API_KEY.")
			self.client = QdrantClient(url=url, api_key=self.cfg.QDRANT_API_KEY)

	@retry_on_qdrant_error
	def ensure_collection(self, collection_name: str) -> None:
		"""Create a collection if it does not exist with the standard B760 vector schema."""
		if not self.client.collection_exists(collection_name):
			self.client.create_collection(
				collection_name=collection_name,
				vectors_config=models.VectorParams(size=self.cfg.VECTOR_SIZE, distance=models.Distance.COSINE),
			)
			self.client.create_payload_index(collection_name=collection_name, field_name="immune", field_schema=models.PayloadSchemaType.BOOL)
			self.client.create_payload_index(collection_name=collection_name, field_name="importance", field_schema=models.PayloadSchemaType.FLOAT)
			logger.info(f"Ghost Collection created: {collection_name}")
			get_event_bus().emit(CollectionCreatedEvent(collection_name=collection_name))

	@retry_on_qdrant_error
	def upsert(self, collection_name: str, points: List[models.PointStruct]) -> None:
		self.client.upsert(collection_name=collection_name, points=points)

	@retry_on_qdrant_error
	def retrieve(self, collection_name: str, ids: List[Any], with_payload: bool = True, with_vectors: bool = False) -> List[Any]:
		return self.client.retrieve(collection_name=collection_name, ids=ids, with_payload=with_payload, with_vectors=with_vectors)

	@retry_on_qdrant_error
	def set_payload(self, collection_name: str, payload: dict[str, Any], points: list[Any]) -> None:
		self.client.set_payload(collection_name=collection_name, payload=payload, points=points)

	@retry_on_qdrant_error
	def batch_update_points(self, collection_name: str, update_operations: List[Any]) -> None:
		self.client.batch_update_points(collection_name=collection_name, update_operations=update_operations)

	@retry_on_qdrant_error
	def scroll(
		self,
		collection_name: str,
		scroll_filter: Optional[models.Filter] = None,
		limit: int = 100,
		with_payload: bool = True,
		with_vectors: bool = False,
		offset: Any = None,
	) -> tuple[List[Any], Any]:
		return self.client.scroll(
			collection_name=collection_name,
			scroll_filter=scroll_filter,
			limit=limit,
			offset=offset,
			with_payload=with_payload,
			with_vectors=with_vectors,
		)

	def scroll_generator(
		self,
		collection: str,
		scroll_filter: Optional[models.Filter] = None,
		limit: int = 100,
		with_payload: bool = True,
		with_vectors: bool = False,
		max_iterations: int = 1000,
	) -> Generator[List[Any], None, None]:
		offset = None
		iterations = 0
		while True:
			iterations += 1
			if iterations > max_iterations:
				break
			try:
				response = self.scroll(
					collection_name=collection,
					scroll_filter=scroll_filter,
					limit=limit,
					offset=offset,
					with_payload=with_payload,
					with_vectors=with_vectors,
				)
			except Exception as e:
				logger.error(f"Scroll operation failed in {collection}: {_mask_pii_exception(e)}")
				break

			yield response[0]

			offset = response[1]
			if offset is None:
				break

	@retry_on_qdrant_error
	def delete(self, collection_name: str, points_selector: Any) -> None:
		self.client.delete(collection_name=collection_name, points_selector=points_selector)

	@retry_on_qdrant_error
	def query_points(
		self,
		collection_name: str,
		query: List[float],
		query_filter: Optional[models.Filter] = None,
		limit: int = 3,
		with_payload: bool = True,
		with_vectors: bool = False,
	) -> Any:
		return self.client.query_points(
			collection_name=collection_name, query=query, query_filter=query_filter, limit=limit, with_payload=with_payload, with_vectors=with_vectors
		)

	@retry_on_qdrant_error
	def collection_exists(self, collection_name: str) -> bool:
		return self.client.collection_exists(collection_name)

	@retry_on_qdrant_error
	def delete_collection(self, collection_name: str) -> None:
		self.client.delete_collection(collection_name=collection_name)

	@retry_on_qdrant_error
	def create_snapshot(self, collection_name: str) -> Any:
		return self.client.create_snapshot(collection_name=collection_name)

	@retry_on_qdrant_error
	def get_collection(self, collection_name: str) -> Any:
		return self.client.get_collection(collection_name=collection_name)
