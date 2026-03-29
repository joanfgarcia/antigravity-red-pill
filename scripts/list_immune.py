import os
import sys
from qdrant_client import QdrantClient
from qdrant_client.http import models

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
import red_pill.config as cfg

client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)

# Use scroll to find all immune points
res, _ = client.scroll(
    collection_name="social_memories",
    scroll_filter=models.Filter(
        must=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]
    ),
    limit=10,
    with_payload=True
)

for p in res:
    print(f"ID: {p.id}")
    print(f"Content (snippet): {str(p.payload.get('content'))[:50]}...")
    print(f"Immune: {p.payload.get('immune')}")
    print(f"Score: {p.payload.get('reinforcement_score')}")
    print("-" * 20)
