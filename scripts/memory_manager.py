#!/usr/bin/env python3
# Execution: uv run --with qdrant-client --with fastembed python3 memory_manager.py [add|search|erode] [work|social] [text/query/session_type]
import sys
import json
import time
from qdrant_client import QdrantClient
from qdrant_client.http import models
from config import QDRANT_URL, EMBEDDING_MODEL, REINFORCEMENT_INCREMENT, EROSION_RATE

client = QdrantClient(url=QDRANT_URL)

try:
    # Quick health check
    client.get_collections()
except Exception as e:
    print(f"CRITICAL ERROR: Qdrant is not available at {QDRANT_URL}.")
    print("Please ensure the podman container is running ('systemctl --user start qdrant').")
    print(f"Details: {e}")
    sys.exit(1)

try:
    from fastembed import TextEmbedding
    encoder = TextEmbedding(model_name=EMBEDDING_MODEL)
except ImportError:
    encoder = None

def add_memory(collection, text, importance=1.0, metadata=None):
    if metadata is None:
        metadata = {}
    
    if encoder:
        vector = list(encoder.embed([text]))[0].tolist()
    else:
        vector = [0.0] * 384 # Placeholder
    
    payload = {
        "content": text,
        "importance": importance,
        "reinforcement_score": 1.0,
        "created_at": time.time(),
        "last_recalled_at": time.time(),
        **metadata
    }
    
    client.upsert(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=int(time.time() * 1000),
                vector=vector,
                payload=payload
            )
        ]
    )
    print(f"Memory added to {collection}")

def search_and_reinforce(collection, query_text, limit=3):
    if encoder:
        vector = list(encoder.embed([query_text]))[0].tolist()
    else:
        vector = [0.0] * 384

    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        with_payload=True
    )
    
    results = response.points
    
    for hit in results:
        score = hit.payload.get("reinforcement_score", 1.0)
        new_score = round(score + REINFORCEMENT_INCREMENT, 2)
        last_recall = time.time()
        
        client.set_payload(
            collection_name=collection,
            payload={
                "reinforcement_score": new_score,
                "last_recalled_at": last_recall
            },
            points=[hit.id],
            wait=True
        )
    
    return results

def apply_erosion(collection, session_type="standard"):
    """
    Applies temporal erosion to all non-immune memories in the collection.
    session_type: "standard", "dense", or "resilient"
    """
    rate = EROSION_RATE
    if session_type == "dense":
        rate = 0.05
    elif session_type == "resilient":
        rate = 0.0
        print("Resilience Shield Active: Skipping erosion.")
        return

    print(f"Applying erosion to {collection} (rate: {rate})...")
    
    offset = None
    eroded_count = 0
    forgotten_count = 0
    
    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=100,
            with_payload=True,
            with_vectors=False,
            offset=offset
        )
        
        for point in points:
            if point.payload.get("immune"):
                continue
            
            current_score = point.payload.get("reinforcement_score", 1.0)
            new_score = round(max(0.0, current_score - rate), 2)
            
            if new_score <= 0.0:
                client.delete(
                    collection_name=collection,
                    points_selector=models.PointIdsList(points=[point.id])
                )
                forgotten_count += 1
            else:
                client.set_payload(
                    collection_name=collection,
                    payload={"reinforcement_score": new_score},
                    points=[point.id]
                )
                eroded_count += 1
        
        offset = next_offset
        if offset is None:
            break
            
    print(f"Erosion complete. Eroded: {eroded_count} | Forgotten: {forgotten_count}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./memory_manager.py [add|search|erode] [work|social] [content/session_type]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    collection_type = sys.argv[2]
    collection = "social_memories" if collection_type == "social" else "work_memories"
    content = " ".join(sys.argv[3:])
    
    if cmd == "add":
        add_memory(collection, content)
    elif cmd == "search":
        results = search_and_reinforce(collection, content)
        for i, hit in enumerate(results):
            print(f"[{i}] Score: {hit.score:.4f} | Reinforcement: {hit.payload.get('reinforcement_score', 0):.2f}")
            print(f"Content: {hit.payload.get('content')}\n")
    elif cmd == "erode":
        session_type = content if content in ["dense", "resilient"] else "standard"
        apply_erosion(collection, session_type)
