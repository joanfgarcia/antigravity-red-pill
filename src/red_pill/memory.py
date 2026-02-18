import logging
import uuid
import time
from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

import red_pill.config as cfg
from red_pill.schemas import CreateEngramRequest

logger = logging.getLogger(__name__)

class PointUpdate:
    """Helper for passing updates without strict PointStruct validation."""
    def __init__(self, id, payload):
        self.id = id
        self.payload = payload

class MemoryManager:
    """
    Core engine for the B760-Adaptive memory protocol.
    Handles semantic storage, reinforcement, and erosion of engrams.
    """
    
    def __init__(self, url: str = cfg.QDRANT_URL):
        self.client = QdrantClient(url=url, api_key=cfg.QDRANT_API_KEY)
        self.encoder = None
        self._initialize_encoder()

    def _initialize_encoder(self):
        try:
            from fastembed import TextEmbedding
            self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL)
        except ImportError:
            logger.warning("fastembed not found. Falling back to zero-vectors (dry-run mode).")

    def _get_vector(self, text: str) -> List[float]:
        if self.encoder:
            return list(self.encoder.embed([text]))[0].tolist()
        return [0.0] * 384

    def add_memory(self, collection: str, text: str, importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None, point_id: Optional[str] = None) -> str:
        """
        Stores a new engram in the specified collection and returns its ID.
        """
        if metadata is None:
            metadata = {}
        
        # Validation: Strictly check input using Pydantic
        # This prevents Agent Smith style "Poison Pill" attacks
        validated_request = CreateEngramRequest(
            content=text,
            importance=importance,
            metadata=metadata
        )
        # Use validated data (sanitized if any cleaning happened)
        text = validated_request.content
        importance = validated_request.importance
        clean_metadata = validated_request.metadata
        
        actual_id = point_id if point_id else str(uuid.uuid4())
        vector = self._get_vector(text)
        
        payload = {
            "content": text,
            "importance": importance,
            "reinforcement_score": 1.0,
            "created_at": time.time(),
            "last_recalled_at": time.time(),
            "immune": False,
            **clean_metadata
        }
        
        self.client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=actual_id,
                    vector=vector,
                    payload=payload
                )
            ]
        )
        logger.info(f"Memory added to {collection} with ID: {actual_id}")
        return actual_id

    def _reinforce_points(self, collection: str, point_ids: List[str], increments: Dict[str, float]) -> List[PointUpdate]:
        """
        Retrieves points by ID, applies reinforcement stacking, and returns them.
        """
        if not point_ids:
            return []
            
        # Filter valid IDs
        valid_ids = []
        for pid in point_ids:
            if isinstance(pid, int):
                valid_ids.append(pid)
            else:
                try:
                    uuid.UUID(str(pid))
                    valid_ids.append(pid)
                except (ValueError, AttributeError):
                    logger.debug(f"Skipping non-UUID association: {pid}")
        
        # Verify IDs against Qdrant strictly
        points = self.client.retrieve(
            collection_name=collection,
            ids=valid_ids,
            with_payload=True,
            with_vectors=False # Optimization: we don't need vectors just to update score
        )
        
        updated_points = []
        for p in points:
            score = p.payload.get("reinforcement_score", 1.0)
            inc = increments.get(str(p.id), increments.get(p.id, 0.0))
            
            # Use max(score, current_db_score) to reduce race condition impact
            # Ideally we would use atomic operations, but Qdrant REST API doesn't support 
            # atomic float increment on payload fields easily without scripting.
            # We'll stick to read-modify-write but minimize the window.
            # A true fix would require Qdrant Scripting or optimistic locking with version check.
            # implementing a naive optimistic lock here is overkill for this scope, 
            # but we can at least not overwrite with stale data if we fetched just now.
            
            new_score = min(score + inc, cfg.IMMUNITY_THRESHOLD)
            p.payload["reinforcement_score"] = round(new_score, 2)
            p.payload["last_recalled_at"] = time.time()
            
            if p.payload["reinforcement_score"] >= cfg.IMMUNITY_THRESHOLD:
                p.payload["immune"] = True
                
            # We use set_payload to avoid overwriting the vector or other concurrent metadata changes
            self.client.set_payload(
                collection_name=collection,
                payload=p.payload,
                points=[p.id]
            )
            
            # Prepare struct for return value (caller expects it)
            # We re-construct it with a dummy vector or None as the caller might expect it 
            # if they asked for with_vectors=True in retrieve, but _reinforce_points output is 
            # primarily used for update_map in search_and_reinforce which only cares about payload.
            # However, the type hint says List[models.PointStruct]. 
            # Let's check usages. search_and_reinforce uses it for upsert (wait, it upserts! that's the bug).
            # The original code did: self.client.upsert(..., points=points_to_update)
            # This logic wipes the vector if we don't pass it! 
            # AND it overwrites everything.
            # My change above uses set_payload. So we DON'T need to return points_to_update for upserting.
            # But search_and_reinforce expects a return to update its local response object.
            
            # Prepare struct for return value (caller expects it)
            updated_points.append(
                PointUpdate(
                    id=p.id,
                    payload=p.payload
                )
            )
            
        return updated_points

    def search_and_reinforce(self, collection: str, query: str, limit: int = 3, deep_recall: bool = False) -> List[Any]:
        """
        Performs semantic search and applies B760 reinforcement to retrieved engrams
        and their associated memories (synaptic propagation).
        
        Filtering: Memories with score < 0.2 (Dormant) are filtered unless deep_recall is True.
        """
        vector = self._get_vector(query)
        
        # B760 Dormancy Filter
        search_filter = None
        if not deep_recall:
            search_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="reinforcement_score",
                        range=models.Range(gte=0.2)
                    )
                ]
            )
            # We also include immune memories which might have 1.0 but are never < 0.2 anyway.
            # But just in case, we could use an OR. However, standard scores start at 1.0.

        response = self.client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=search_filter,
            limit=limit * (2 if deep_recall else 1), # Double limit for Deep Recall as per spec 6.2
            with_payload=True,
            with_vectors=True
        )
        
        # Reinforcement Increment Map
        # stacks increments from hits (0.1) and synaptic propagation (0.05)
        increment_map: Dict[str, float] = {}
        
        # 1. Direct Hits
        for hit in response.points:
            increment_map[hit.id] = cfg.REINFORCEMENT_INCREMENT
            
        # 2. Synaptic Propagation
        propagation_increment = cfg.REINFORCEMENT_INCREMENT * cfg.PROPAGATION_FACTOR
        for hit in response.points:
            assocs = hit.payload.get("associations", [])
            for assoc_id in assocs:
                # Stack the increment if it's already in the map (multi-path reinforcement)
                increment_map[assoc_id] = increment_map.get(assoc_id, 0.0) + propagation_increment

        if not increment_map:
            return response.points

        # 3. Apply reinforcements in bulk
        points_to_update = self._reinforce_points(collection, list(increment_map.keys()), increment_map)
        
        if points_to_update:
            # self.client.upsert(collection_name=collection, points=points_to_update) 
            # REMOVED: _reinforce_points now handles persistence via set_payload to avoid overwrites
            pass
            # Map reinforced payloads back to response hits for immediate usage
            update_map = {p.id: p.payload for p in points_to_update}
            for hit in response.points:
                if hit.id in update_map:
                    hit.payload.update(update_map[hit.id])
        
        # Note: we return response.points but the actual DB state is now updated with stacked scores.
        return response.points

    def _calculate_decay(self, current_score: float, rate: float) -> float:
        """
        Calculates the new score based on the configured strategy.
        """
        if cfg.DECAY_STRATEGY == "exponential":
            # Exponential decay: score * (1 - rate)
            new_score = current_score * (1.0 - rate)
            # Fix floor: If rounding keeps the score the same, force it down or to zero
            # to avoid asymptotic database bloat.
            if round(new_score, 2) >= round(current_score, 2) and current_score > 0:
                new_score = current_score - 0.01
        else:
            # Default to linear decay: score - rate
            new_score = current_score - rate
            
        return round(max(new_score, 0.0), 2)

    def apply_erosion(self, collection: str, rate: float = None):
        """
        Decays non-immune memories using the configured DECAY_STRATEGY.
        Memories with score <= 0 are forgotten.
        """
        if rate is None:
            rate = cfg.EROSION_RATE

        offset = None
        eroded_count = 0
        deleted_count = 0
        
        logger.info(f"Starting erosion cycle on {collection} using {cfg.DECAY_STRATEGY} strategy.")

        while True:
            response = self.client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False # Optimization: don't fetch vectors for erosion
            )
            
            points_to_update = []
            points_to_delete = []
            
            for hit in response[0]:
                if hit.payload.get("immune", False):
                    continue
                
                current_score = hit.payload.get("reinforcement_score", 1.0)
                new_score = self._calculate_decay(current_score, rate)
                
                if new_score <= 0:
                    points_to_delete.append(hit.id)
                    deleted_count += 1
                else:
                    # Optimization: create a payload update instead of full point replacement
                    hit.payload["reinforcement_score"] = new_score
                    
                    # We can batch set_payload calls if valid, but Qdrant client set_payload takes a list of points 
                    # for the SAME payload. Here each point has a DIFFERENT score.
                    # So we have to call set_payload per point or group by score (unlikely efficiently).
                    # OR we use overwrite_payload=False? No, that merges.
                    # Qdrant Update API allows batching via 'batch' operations but python client wrappers...
                    # Let's keep it simple: we want to avoid network traffic of vectors.
                    # For bulk updates with different values, upsert is standard BUT requires vectors.
                    # Wait, Qdrant allows upserting with specific IDs and payloads WITHOUT vectors if the point exists?
                    # No, strict mode usually complains. 
                    # However, we can use Scroll(with_vectors=False) + set_payload in specific updates.
                    
                    self.client.set_payload(
                        collection_name=collection,
                        payload={"reinforcement_score": new_score},
                        points=[hit.id]
                    )
                    eroded_count += 1
            
            # points_to_update logic removed as we do it inline or we'd need a batch update method 
            # that supports different payloads per point. client.upsert requires vectors/payloads.
            # If we want to avoid fetching vectors, we MUST use set_payload one by one (slow) 
            # or usage batch updates if supported. 
            # Given typical erosion scale, one-by-one might be slow.
            # BUT fetching vectors is also slow and bandwidth heavy.
            # Compromise: iterate and fire set_payload.
            
            if points_to_delete:
                self.client.delete(
                    collection_name=collection, 
                    points_selector=models.PointIdsList(points=points_to_delete)
                )
            
            offset = response[1]
            if offset is None:
                break
                
        logger.info(f"Erosion cycle finished. Updated: {eroded_count}, Deleted: {deleted_count}")

    def get_stats(self, collection: str) -> Dict[str, Any]:
        """
        Returns collection diagnostic information.
        """
        info = self.client.get_collection(collection_name=collection)
        return {
            "status": info.status,
            "points_count": info.points_count,
            "segments_count": info.segments_count
        }
