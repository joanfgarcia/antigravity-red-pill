import logging
import uuid
import time
from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

from red_pill.config import QDRANT_URL, EMBEDDING_MODEL, EROSION_RATE, REINFORCEMENT_INCREMENT, IMMUNITY_THRESHOLD

logger = logging.getLogger(__name__)

class MemoryManager:
    """
    Core engine for the B760-Adaptive memory protocol.
    Handles semantic storage, reinforcement, and erosion of engrams.
    """
    
    def __init__(self, url: str = QDRANT_URL):
        self.client = QdrantClient(url=url)
        self.encoder = None
        self._initialize_encoder()

    def _initialize_encoder(self):
        try:
            from fastembed import TextEmbedding
            self.encoder = TextEmbedding(model_name=EMBEDDING_MODEL)
        except ImportError:
            logger.warning("fastembed not found. Falling back to zero-vectors (dry-run mode).")

    def _get_vector(self, text: str) -> List[float]:
        if self.encoder:
            return list(self.encoder.embed([text]))[0].tolist()
        return [0.0] * 384

    def add_memory(self, collection: str, text: str, importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None):
        """
        Stores a new engram in the specified collection.
        """
        if metadata is None:
            metadata = {}
        
        vector = self._get_vector(text)
        
        payload = {
            "content": text,
            "importance": importance,
            "reinforcement_score": 1.0,
            "created_at": time.time(),
            "last_recalled_at": time.time(),
            "immune": False,
            **metadata
        }
        
        self.client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload
                )
            ]
        )
        logger.info(f"Memory added to {collection}")

    def search_and_reinforce(self, collection: str, query: str, limit: int = 3) -> List[Any]:
        """
        Performs semantic search and applies B760 reinforcement to retrieved engrams.
        """
        vector = self._get_vector(query)

        response = self.client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            with_payload=True
        )
        
        points_to_update = []
        for hit in response.points:
            score = hit.payload.get("reinforcement_score", 1.0)
            # Apply B760 reinforcement
            new_score = min(score + REINFORCEMENT_INCREMENT, IMMUNITY_THRESHOLD)
            hit.payload["reinforcement_score"] = round(new_score, 2)
            hit.payload["last_recalled_at"] = time.time()
            
            # Immunity check
            if hit.payload["reinforcement_score"] >= IMMUNITY_THRESHOLD:
                hit.payload["immune"] = True
                logger.info(f"Memory {hit.id} promoted to IMMUNE status.")
            
            points_to_update.append(
                models.PointStruct(
                    id=hit.id,
                    vector=hit.vector if hasattr(hit, 'vector') and hit.vector else vector,
                    payload=hit.payload
                )
            )
        
        if points_to_update:
            self.client.upsert(collection_name=collection, points=points_to_update)
        
        return response.points

    def apply_erosion(self, collection: str, rate: float = EROSION_RATE):
        """
        Decays non-immune memories. Memories with score <= 0 are forgotten.
        """
        offset = None
        eroded_count = 0
        deleted_count = 0
        
        while True:
            response = self.client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=True
            )
            
            points_to_update = []
            points_to_delete = []
            
            for hit in response[0]:
                if hit.payload.get("immune", False):
                    continue
                
                current_score = hit.payload.get("reinforcement_score", 1.0)
                new_score = round(max(current_score - rate, 0.0), 2)
                
                if new_score <= 0:
                    points_to_delete.append(hit.id)
                    deleted_count += 1
                else:
                    hit.payload["reinforcement_score"] = new_score
                    points_to_update.append(
                        models.PointStruct(
                            id=hit.id,
                            vector=hit.vector,
                            payload=hit.payload
                        )
                    )
                    eroded_count += 1
            
            if points_to_update:
                self.client.upsert(collection_name=collection, points=points_to_update)
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
