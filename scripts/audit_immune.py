import os
import sys
from qdrant_client import QdrantClient
from qdrant_client.http import models

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
import red_pill.config as cfg

client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)

# Monitor for potential immunity loss
collections = ["work_memories", "social_memories", "directive_memories"]
for coll in collections:
    print(f"Checking {coll}...")
    res, _ = client.scroll(
        collection_name=coll,
        limit=100,
        with_payload=True
    )
    for p in res:
        score = p.payload.get("reinforcement_score", 0.0)
        immune = p.payload.get("immune")
        if score >= 10.0 and not immune:
            print(f"BUG DETECTED: Point {p.id} has high score ({score}) but immune is {immune}")
            print(f"Content: {str(p.payload.get('content'))[:50]}")
