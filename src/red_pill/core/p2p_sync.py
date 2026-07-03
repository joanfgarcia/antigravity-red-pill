import base64
import datetime
import gzip
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

import red_pill.config as cfg

logger = logging.getLogger(__name__)


def to_sqlite_timestamp(ts: float) -> str:
	return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def from_sqlite_timestamp(ts_str: str) -> float:
	try:
		for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
			try:
				dt = datetime.datetime.strptime(ts_str.strip(), fmt)
				return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
			except ValueError:
				continue
	except Exception:
		pass
	return 0.0


def get_point_modification_time(payload: dict) -> float:
	return float(payload.get("updated_at", max(payload.get("created_at", 0.0), payload.get("last_recalled_at", 0.0))))


def resolve_peer_id(peer_name_or_id: str) -> str:
	from red_pill.core.paths import get_config_dir

	peers_file = get_config_dir() / "peers.json"
	if peers_file.exists():
		try:
			with open(peers_file, "r") as f:
				peers = json.load(f)
			if peer_name_or_id in peers:
				return str(peers[peer_name_or_id])
		except Exception:
			pass
	return peer_name_or_id


def _known_peer_identifiers() -> set:
	"""All accepted peer identifiers (aliases AND node ids) from peers.json."""
	from red_pill.core.paths import get_config_dir

	peers_file = get_config_dir() / "peers.json"
	if not peers_file.exists():
		return set()
	try:
		with open(peers_file, "r") as f:
			peers = json.load(f)
		return set(peers.keys()) | {str(v) for v in peers.values()}
	except Exception:
		return set()


def _is_authorized_originator(originator: Optional[str]) -> bool:
	"""Defense-in-depth: a sync payload is only applied if its originator is a known peer.

	Sync chunks flow inbox → cognitive_tasks → autonomous execution, so an unauthenticated
	upstream (e.g. neon-link with an open/misconfigured bridge) must not be able to inject
	executable sync. Gated by P2P_SYNC_REQUIRE_KNOWN_PEER (default True). When enforcing, a
	missing originator or one absent from peers.json is rejected (fail closed).
	"""
	if not getattr(cfg, "P2P_SYNC_REQUIRE_KNOWN_PEER", True):
		return True
	if not originator:
		return False
	return originator in _known_peer_identifiers()


def add_peer_alias(alias: str, node_id: str) -> None:
	from red_pill.core.paths import get_config_dir

	config_dir = get_config_dir()
	os.makedirs(config_dir, exist_ok=True)
	peers_file = config_dir / "peers.json"

	peers = {}
	if peers_file.exists():
		try:
			with open(peers_file, "r") as f:
				peers = json.load(f)
		except Exception:
			pass

	peers[alias] = node_id
	with open(peers_file, "w") as f:
		json.dump(peers, f, indent=4)


def get_local_public_key() -> str:
	from red_pill.core.paths import get_neon_link_config_dir, get_neon_link_data_dir

	try:
		from pure_mls.keys import SignatureKey
	except ImportError:
		return "UNKNOWN (pure-mls not available)"

	paths_to_try = [
		get_neon_link_config_dir() / "neon_link.seed",
		get_neon_link_data_dir() / "neon_link.seed",
		Path.home() / "Documents/IA/neon-link/storage/neon_link.seed",
	]
	for p in paths_to_try:
		if p.exists():
			try:
				with open(p, "rb") as f:
					seed = f.read(32)
				sig_key = SignatureKey.from_private_bytes(seed)
				return sig_key.public_bytes().hex()
			except Exception:
				pass
	return "UNKNOWN (seed file not found)"


class SovereignSyncEngine:
	def __init__(self, db_path: str, qdrant_client: QdrantClient):
		self.db_path = db_path
		self.qdrant_client = qdrant_client
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		CognitiveQueueManager(db_path=self.db_path)

	@classmethod
	def from_default(cls) -> "SovereignSyncEngine":
		from red_pill.core.paths import get_queue_dir

		db_path = str(get_queue_dir() / "bunker_queue.db")
		client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
		return cls(db_path, client)

	def get_sqlite_delta(self, last_sync_timestamp: float) -> List[Dict[str, Any]]:
		ts_str = to_sqlite_timestamp(last_sync_timestamp)
		with sqlite3.connect(self.db_path) as conn:
			conn.row_factory = sqlite3.Row
			cursor = conn.cursor()
			cursor.execute(
				"SELECT id, source, priority, payload, status, parent_task_id, created_at, updated_at, attempts, error_log FROM cognitive_tasks WHERE updated_at > ?",
				(ts_str,),
			)
			return [dict(row) for row in cursor.fetchall()]

	def apply_sqlite_delta(self, delta: List[Dict[str, Any]]) -> None:
		if not delta:
			return
		with sqlite3.connect(self.db_path) as conn:
			conn.row_factory = sqlite3.Row
			for task in delta:
				cursor = conn.cursor()
				cursor.execute("SELECT updated_at FROM cognitive_tasks WHERE id = ?", (task["id"],))
				row = cursor.fetchone()
				if row:
					existing_ts = from_sqlite_timestamp(row["updated_at"])
					incoming_ts = from_sqlite_timestamp(task["updated_at"])
					if incoming_ts <= existing_ts:
						continue

					cursor.execute(
						"""
						UPDATE cognitive_tasks
						SET source = ?, priority = ?, payload = ?, status = ?, parent_task_id = ?,
							created_at = ?, updated_at = ?, attempts = ?, error_log = ?
						WHERE id = ?
						""",
						(
							task["source"],
							task["priority"],
							task["payload"],
							task["status"],
							task["parent_task_id"],
							task["created_at"],
							task["updated_at"],
							task["attempts"],
							task["error_log"],
							task["id"],
						),
					)
				else:
					cursor.execute(
						"""
						INSERT INTO cognitive_tasks (id, source, priority, payload, status, parent_task_id, created_at, updated_at, attempts, error_log)
						VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
						""",
						(
							task["id"],
							task["source"],
							task["priority"],
							task["payload"],
							task["status"],
							task["parent_task_id"],
							task["created_at"],
							task["updated_at"],
							task["attempts"],
							task["error_log"],
						),
					)
			conn.commit()

	def get_qdrant_delta(self, collections: List[str], last_sync_timestamp: float) -> Dict[str, Any]:
		delta = {}
		for coll in collections:
			if not self.qdrant_client.collection_exists(coll):
				continue

			coll_info = self.qdrant_client.get_collection(coll)
			vectors_config = coll_info.config.params.vectors
			from qdrant_client.http.models import VectorParams

			if isinstance(vectors_config, VectorParams):
				vector_size = vectors_config.size
				distance = vectors_config.distance.value if hasattr(vectors_config.distance, "value") else str(vectors_config.distance)
			elif isinstance(vectors_config, dict):
				first_val = list(vectors_config.values())[0] if vectors_config else None
				if isinstance(first_val, VectorParams):
					vector_size = first_val.size
					distance = first_val.distance.value if hasattr(first_val.distance, "value") else str(first_val.distance)
				else:
					vector_size = cfg.VECTOR_SIZE
					distance = "Cosine"
			else:
				vector_size = cfg.VECTOR_SIZE
				distance = "Cosine"

			scroll_filter = None
			if last_sync_timestamp > 0:
				scroll_filter = models.Filter(
					should=[
						models.FieldCondition(key="created_at", range=models.Range(gt=last_sync_timestamp)),
						models.FieldCondition(key="last_recalled_at", range=models.Range(gt=last_sync_timestamp)),
					]
				)

			points = []
			offset = None
			while True:
				res_points, next_offset = self.qdrant_client.scroll(
					collection_name=coll, scroll_filter=scroll_filter, limit=100, with_payload=True, with_vectors=True, offset=offset
				)
				for p in res_points:
					payload = p.payload or {}
					pt_time = get_point_modification_time(payload)
					if pt_time > last_sync_timestamp:
						points.append({"id": str(p.id) if isinstance(p.id, uuid.UUID) else p.id, "vector": p.vector, "payload": payload})
				offset = next_offset
				if offset is None:
					break

			if points:
				delta[coll] = {"points": points, "vector_size": vector_size, "distance": distance}
		return delta

	def apply_qdrant_delta(self, delta: Dict[str, Any]) -> None:
		for coll, coll_data in delta.items():
			points_data = coll_data.get("points", [])
			if not points_data:
				continue

			if not self.qdrant_client.collection_exists(coll):
				vector_size = coll_data.get("vector_size", cfg.VECTOR_SIZE)
				distance_str = coll_data.get("distance", "Cosine")
				dist_enum = models.Distance.COSINE
				if distance_str.upper() == "EUCLID":
					dist_enum = models.Distance.EUCLID
				elif distance_str.upper() == "DOT":
					dist_enum = models.Distance.DOT

				self.qdrant_client.create_collection(collection_name=coll, vectors_config=models.VectorParams(size=vector_size, distance=dist_enum))
				self.qdrant_client.create_payload_index(collection_name=coll, field_name="immune", field_schema=models.PayloadSchemaType.BOOL)
				self.qdrant_client.create_payload_index(collection_name=coll, field_name="importance", field_schema=models.PayloadSchemaType.FLOAT)

			incoming_ids = [p["id"] for p in points_data]

			typed_ids = []
			for idx in incoming_ids:
				try:
					typed_ids.append(uuid.UUID(idx))
				except (ValueError, TypeError):
					typed_ids.append(idx)

			existing_points = {}
			try:
				retrieved = self.qdrant_client.retrieve(collection_name=coll, ids=typed_ids, with_payload=True, with_vectors=False)
				for ep in retrieved:
					existing_points[str(ep.id)] = ep
			except Exception as e:
				logger.warning(f"Failed to retrieve existing points for LWW check: {e}")

			points_to_upsert = []
			for p in points_data:
				pid_str = str(p["id"])
				payload = p["payload"] or {}
				vector = p["vector"]

				if vector is None:
					continue

				if pid_str in existing_points:
					existing_payload = existing_points[pid_str].payload or {}
					existing_ts = get_point_modification_time(existing_payload)
					incoming_ts = get_point_modification_time(payload)
					if incoming_ts <= existing_ts:
						continue

				try:
					point_id = uuid.UUID(p["id"])
				except (ValueError, TypeError):
					point_id = p["id"]

				points_to_upsert.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

			if points_to_upsert:
				self.qdrant_client.upsert(collection_name=coll, points=points_to_upsert)

	def generate_sync_payload(self, collections: List[str], last_sync_timestamp: float) -> bytes:
		sqlite_delta = self.get_sqlite_delta(last_sync_timestamp)
		qdrant_delta = self.get_qdrant_delta(collections, last_sync_timestamp)
		payload_dict = {"sqlite": sqlite_delta, "qdrant": qdrant_delta, "timestamp": time.time()}
		raw_json = json.dumps(payload_dict)
		compressed = gzip.compress(raw_json.encode("utf-8"))
		return compressed

	def apply_sync_payload(self, compressed_payload: bytes) -> None:
		decompressed = gzip.decompress(compressed_payload).decode("utf-8")
		payload_dict = json.loads(decompressed)

		sqlite_delta = payload_dict.get("sqlite", [])
		self.apply_sqlite_delta(sqlite_delta)

		qdrant_delta = payload_dict.get("qdrant", {})
		self.apply_qdrant_delta(qdrant_delta)

	def transmit_sync_payload(self, target_peer: str, collections: List[str], last_sync_timestamp: float) -> str | None:
		payload = self.generate_sync_payload(collections, last_sync_timestamp)
		transmitter = ChunkedPayloadTransmitter()
		chunks = transmitter.chunk_payload(payload)

		from red_pill.core.paths import get_neon_link_db_path

		db_path = get_neon_link_db_path()
		resolved_peer = resolve_peer_id(target_peer)

		with sqlite3.connect(str(db_path)) as conn:
			cursor = conn.cursor()
			for chunk in chunks:
				payload_json = json.dumps({"text": json.dumps(chunk), "mode": "background", "priority": "normal", "group_size": 2})
				cursor.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES (?, ?, ?)", ("rings", resolved_peer, payload_json))
			conn.commit()

		logger.info(f"Enqueued {len(chunks)} sync chunks for peer {target_peer} (session: {chunks[0]['session_id']})")
		return chunks[0]["session_id"] if chunks else None

	def process_incoming_syncs(self) -> int:
		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		unread = inbox.get_unread(limit=100)

		transmitter = ChunkedPayloadTransmitter()
		chunks_by_session: dict[str, list[tuple[dict, int]]] = {}
		reports_to_mark = []

		for report in unread:
			# Defense-in-depth: only apply sync from a known peer. Blocks the
			# unauthenticated-ingress → cognitive_tasks → autonomous-exec chain.
			if not _is_authorized_originator(report.get("originator")):
				logger.warning(f"Rejected sync report from unknown originator: {report.get('originator')!r}")
				continue
			content = report.get("content", "")
			json_str = None
			if content.strip().startswith("{") and content.strip().endswith("}"):
				json_str = content.strip()
			elif "Message from" in content and ":" in content:
				idx = content.find("{")
				if idx != -1:
					json_str = content[idx:].strip()

			if not json_str:
				continue

			try:
				chunk_data = json.loads(json_str)
				if all(k in chunk_data for k in ("session_id", "chunk_index", "total_chunks", "payload", "sha256")):
					session_id = chunk_data["session_id"]
					if session_id not in chunks_by_session:
						chunks_by_session[session_id] = []
					chunks_by_session[session_id].append((chunk_data, report["id"]))
			except Exception:
				continue

		applied_count = 0
		for session_id, chunk_list in chunks_by_session.items():
			first_chunk = chunk_list[0][0]
			total_chunks = first_chunk["total_chunks"]
			if len(chunk_list) == total_chunks:
				chunk_list.sort(key=lambda x: x[0]["chunk_index"])

				try:
					payload_bytes = None
					for chunk_data, report_id in chunk_list:
						payload_bytes = transmitter.receive_chunk(chunk_data)
						reports_to_mark.append(report_id)

					if payload_bytes:
						self.apply_sync_payload(payload_bytes)
						applied_count += 1
						logger.info(f"Successfully applied P2P Sync Session {session_id}")
				except Exception as e:
					logger.error(f"Failed to apply sync session {session_id}: {e}")

		if reports_to_mark:
			inbox.mark_as_read(reports_to_mark)

		return applied_count


class ChunkedPayloadTransmitter:
	def __init__(self, chunk_size: int = 400 * 1024):
		self.chunk_size = chunk_size
		self.assemblers: Dict[str, Dict[int, str]] = {}

	def chunk_payload(self, payload: bytes) -> List[Dict[str, Any]]:
		session_id = str(uuid.uuid4())
		b64_str = base64.b64encode(payload).decode("utf-8")
		total_len = len(b64_str)

		chunks = []
		chunk_idx = 0
		start = 0
		while start < total_len:
			end = min(start + self.chunk_size, total_len)
			chunk_data = b64_str[start:end]
			sha256 = hashlib.sha256(chunk_data.encode("utf-8")).hexdigest()
			chunks.append({"session_id": session_id, "chunk_index": chunk_idx, "total_chunks": 0, "payload": chunk_data, "sha256": sha256})
			chunk_idx += 1
			start = end

		total_chunks = len(chunks)
		for c in chunks:
			c["total_chunks"] = total_chunks

		return chunks

	def receive_chunk(self, chunk: Dict[str, Any]) -> Optional[bytes]:
		session_id = chunk["session_id"]
		chunk_idx = chunk["chunk_index"]
		total_chunks = chunk["total_chunks"]
		payload = chunk["payload"]
		sha256 = chunk["sha256"]

		expected_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
		if sha256 != expected_sha:
			logger.error(f"Chunk checksum validation failed for session {session_id}, index {chunk_idx}")
			if session_id in self.assemblers:
				del self.assemblers[session_id]
			raise ValueError("Corrupt chunk checksum mismatch")

		if session_id not in self.assemblers:
			self.assemblers[session_id] = {}

		self.assemblers[session_id][chunk_idx] = payload

		if len(self.assemblers[session_id]) == total_chunks:
			assembled_b64 = []
			for idx in range(total_chunks):
				if idx not in self.assemblers[session_id]:
					logger.error(f"Missing chunk index {idx} in session {session_id}")
					del self.assemblers[session_id]
					return None
				assembled_b64.append(self.assemblers[session_id][idx])

			del self.assemblers[session_id]

			full_b64 = "".join(assembled_b64)
			return base64.b64decode(full_b64.encode("utf-8"))

		return None
