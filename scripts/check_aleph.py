import os
import sys

from qdrant_client import QdrantClient

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
import red_pill.config as cfg

client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)

ID_ALEPH = "00000000-0000-0000-0000-000000000001"
res = client.retrieve(collection_name="social_memories", ids=[ID_ALEPH], with_payload=True)

if res:
	print(f"Payload for Aleph: {res[0].payload}")
else:
	print("Aleph not found.")
