import os
import sys
from qdrant_client import QdrantClient
from qdrant_client.http import models

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
import red_pill.config as cfg
from red_pill.memory import MemoryManager

manager = MemoryManager()
client = manager.client

# Aleph
ID_ALEPH = "00000000-0000-0000-0000-000000000001"
res = client.retrieve(collection_name="social_memories", ids=[ID_ALEPH], with_payload=True)

if res:
    raw_payload = res[0].payload
    print(f"RAW Payload Immune: {raw_payload.get('immune')}")
    print(f"RAW Payload Score: {raw_payload.get('reinforcement_score')}")
    
    parsed_payload = manager._parse_payload(raw_payload, strict=True)
    print(f"PARSED Payload Immune: {parsed_payload.get('immune')}")
    print(f"PARSED Payload Score: {parsed_payload.get('reinforcement_score')}")
else:
    print("Aleph not found.")
