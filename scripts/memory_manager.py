#!/usr/bin/env python3
# Execution: uv run --with qdrant-client --with fastembed python3 memory_manager.py [add|search] [work|social] [text]
import sys
import json
import time
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Configuration
QDRANT_URL = "http://localhost:6333"

client = QdrantClient(url=QDRANT_URL)

try:
    # Quick health check
    client.get_collections()
except Exception as e:
    print(f"CRITICAL ERROR: Qdrant is not available at {QDRANT_URL}.")
    print("Please ensure the podman container is running ('systemctl --user start qdrant').")
    print(f"Details: {e}")
    sys.exit(1)

# For 1.15+, we can use query_points which handles inference if configured, 
# or we just pass the text and let it handle it if we have a provider.
# Since we want to be local and fast, we'll stick to manual embedding with fastembed if needed,
# or better yet, since we have the Qdrant MCP server running, we could use that.
# But for this script, we'll use query_points with local embeddings.

try:
    from fastembed import TextEmbedding
    encoder = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
except ImportError:
    encoder = None

def add_memory(collection, text, importance=1.0, metadata=None):
    if metadata is None:
        metadata = {}
    
    if encoder:
        vector = list(encoder.embed([text]))[0].tolist()
    else:
        # Fallback if fastembed is not available (should be in uv run)
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

    # Using query_points (modern API)
    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        with_payload=True
    )
    
    results = response.points
    points_to_update = []
    
    for hit in results:
        # Reinforcement logic
        score = hit.payload.get("reinforcement_score", 1.0)
        hit.payload["reinforcement_score"] = score + 0.1
        hit.payload["last_recalled_at"] = time.time()
        
        points_to_update.append(
            models.PointStruct(
                id=hit.id,
                vector=vector, # In query_points, we don't always get the vector back unless requested
                payload=hit.payload
            )
        )
    
    if points_to_update:
        client.upsert(collection_name=collection, points=points_to_update)
    
    return results

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./memory_manager.py [add|search] [work|social] [text/query]")
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
