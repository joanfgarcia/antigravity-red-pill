#!/usr/bin/env python3
# Execution: uv run --with qdrant-client --with fastembed python3 memory_manager.py [add|search|erode|diag] [work|social] [content/session_type]
import sys
import json
import time
import re
from qdrant_client import QdrantClient
from qdrant_client.http import models
from config import QDRANT_URL, EMBEDDING_MODEL, REINFORCEMENT_INCREMENT, EROSION_RATE

client = QdrantClient(url=QDRANT_URL)

# B760 v3.0 Thresholds
DORMANCY_THRESHOLD = 0.2
DORMANCY_EPSILON = 0.01 # Precision safety
DEEP_RECALL_TRIGGERS = [
    r"recuerda", r"te acuerdas", r"olvidado", r"memoria", 
    r"remember", r"forget", r"recall", r"no puedes", r"en serio"
]

try:
    client.get_collections()
except Exception as e:
    print(f"CRITICAL ERROR: Qdrant is not available at {QDRANT_URL}.")
    sys.exit(1)

try:
    from fastembed import TextEmbedding
    encoder = TextEmbedding(model_name=EMBEDDING_MODEL)
except ImportError:
    encoder = None

def is_deep_recall(query_text):
    """Detects if the query triggers a Deep Recall sequence."""
    query_lower = query_text.lower()
    return any(re.search(pattern, query_lower) for pattern in DEEP_RECALL_TRIGGERS)

def get_synaptic_weight(hit):
    """Calculates weight based on reinforcement and associations."""
    base_score = hit.payload.get("reinforcement_score", 1.0)
    associations = hit.payload.get("associations", [])
    # Associative bonus: +0.05 per active association
    return round(base_score + (len(associations) * 0.05), 2)

def add_memory(collection, text, importance=1.0, associations=None, metadata=None):
    if metadata is None: metadata = {}
    if associations is None: associations = []
    
    if encoder:
        vector = list(encoder.embed([text]))[0].tolist()
    else:
        # Fallback to server-side if client-side encoder fails
        # Assumes collection has an inference model configured
        vector = text 

    payload = {
        "content": text,
        "importance": importance,
        "reinforcement_score": 1.0,
        "associations": associations,
        "created_at": time.time(),
        "last_recalled_at": time.time(),
        "dormant": False,
        **metadata
    }
    
    client.upsert(
        collection_name=collection,
        points=[
            models.PointStruct(
                id=int(time.time() * 1000000),
                vector=vector if isinstance(vector, list) else [0.0]*384, # Simplified fallback
                payload=payload
            )
        ]
    )
    print(f"Memory added to {collection}. Synaptic Initial Load: 1.0")

def search_and_reinforce(collection, query_text, limit=5):
    deep_recall = is_deep_recall(query_text)
    if deep_recall:
        print("!! DEEP RECALL TRIGGERED: Bypassing dormancy filters !!")

    if encoder:
        vector = list(encoder.embed([query_text]))[0].tolist()
    else:
        vector = [0.0] * 384 # Placeholder

    # Apply dormancy filter unless Deep Recall is active
    filter_query = None
    if not deep_recall:
        filter_query = models.Filter(
            must=[
                models.FieldCondition(
                    key="reinforcement_score",
                    range=models.Range(gt=DORMANCY_THRESHOLD + DORMANCY_EPSILON)
                )
            ]
        )

    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=limit if not deep_recall else limit * 2,
        query_filter=filter_query,
        with_payload=True
    )
    
    results = response.points
    
    for hit in results:
        # 1. Reinforce Target
        score = hit.payload.get("reinforcement_score", 1.0)
        new_score = round(score + REINFORCEMENT_INCREMENT, 2)
        
        # 2. Reinforce Associated (Graph Logic)
        associations = hit.payload.get("associations", [])
        for assoc_id in associations:
            try:
                # Propagate 50% of the normal reinforcement to associated engrams
                assoc_hit = client.retrieve(collection_name=collection, ids=[assoc_id])
                if assoc_hit:
                    old_assoc_score = assoc_hit[0].payload.get("reinforcement_score", 1.0)
                    new_assoc_score = round(old_assoc_score + (REINFORCEMENT_INCREMENT * 0.5), 2)
                    client.set_payload(
                        collection_name=collection,
                        payload={"reinforcement_score": new_assoc_score},
                        points=[assoc_id]
                    )
                    print(f" -> Propagated stimulus to linked engram: {assoc_id}")
            except Exception:
                pass 
        
        # 3. Dynamic Structuralization (Immunity Promotion)
        is_immune = hit.payload.get("immune", False)
        if not is_immune and new_score >= 10.0:
            print("Structural threshold reached. Promoting memory to IMMUNE strata.")
            is_immune = True

        client.set_payload(
            collection_name=collection,
            payload={
                "reinforcement_score": new_score,
                "last_recalled_at": time.time(),
                "immune": is_immune,
                "dormant": new_score < DORMANCY_THRESHOLD
            },
            points=[hit.id]
        )
    
    return results

def apply_erosion(collection, session_type="auto"):
    """
    Applies temporal erosion. 
    'auto' calculates load based on session metrics (v3.0).
    """
    rate = EROSION_RATE
    if session_type == "auto":
        # Placeholder for neural load calculation
        # In v3.0 daemon, this will be (searches / additions) / time
        rate = EROSION_RATE 
    elif session_type == "dense":
        rate = 0.1
    elif session_type == "resilient":
        print("Resilience Shield Active.")
        return

    print(f"Applying erosion (rate: {rate})...")
    
    offset = None
    eroded_count = 0
    forgotten_count = 0
    
    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=100,
            with_payload=True,
            offset=offset
        )
        
        for point in points:
            if point.payload.get("immune"): continue
            
            current_score = point.payload.get("reinforcement_score", 1.0)
            new_score = round(max(0.0, current_score - rate), 2)
            
            if new_score <= 0.0:
                client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[point.id]))
                forgotten_count += 1
            else:
                client.set_payload(
                    collection_name=collection,
                    payload={
                        "reinforcement_score": new_score,
                        "dormant": new_score < DORMANCY_THRESHOLD
                    },
                    points=[point.id]
                )
                eroded_count += 1
        
        offset = next_offset
        if offset is None: break
            
    print(f"Erosion complete. Eroded: {eroded_count} | Forgotten: {forgotten_count}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: ./memory_manager.py [add|search|erode|diag] [work|social] [content/args]")
        sys.exit(1)
    
    cmd, coll_type = sys.argv[1:3]
    collection = "social_memories" if coll_type == "social" else "work_memories"
    content = " ".join(sys.argv[3:])
    
    if cmd == "add":
        add_memory(collection, content)
    elif cmd == "search":
        results = search_and_reinforce(collection, content)
        for i, hit in enumerate(results):
            dormant_str = "[DORMANT]" if hit.payload.get("dormant") else ""
            immune_str = "[IMMUNE]" if hit.payload.get("immune") else ""
            print(f"[{i}] {hit.score:.4f} | Reinforcement: {hit.payload.get('reinforcement_score', 0):.2f} {dormant_str}{immune_str}")
            print(f"Content: {hit.payload.get('content')}\n")
    elif cmd == "erode":
        apply_erosion(collection, content if content else "auto")
    elif cmd == "diag":
        info = client.get_collection(collection)
        print(f"Collection: {collection} | Points: {info.points_count} | Status: {info.status}")
