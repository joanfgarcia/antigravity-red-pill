#!/usr/bin/env python3
"""
chronicle_refine.py — Cognitive Refinement Engine.

Applies heuristic normalization and fragmentation to existing 
nodes in the archive_memories collection.
"""

import logging
import uuid
import hashlib
from typing import List, Dict, Any
from red_pill.memory import MemoryManager
from qdrant_client import models

# Use the logic from the ingester
from antigravity_ingest import ChronicleIngester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chronicle_refine")

def main():
    mem = MemoryManager()
    ingester = ChronicleIngester()
    collection = "archive_memories"
    
    logger.info(f"Starting Cognitive Refinement on '{collection}'...")
    
    # Scroll through all nodes that are not fragments
    offset = None
    total_refined = 0
    
    while True:
        response = mem.client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                must_not=[models.FieldCondition(key="type", match=models.MatchValue(value="idea_fragment"))]
            ),
            limit=50,
            with_payload=True,
            with_vectors=False,
            offset=offset
        )
        points, next_offset = response
        if not points:
            break
            
        for p in points:
            payload = p.payload or {}
            raw = payload.get("raw_content", "")
            if not raw: continue
            
            # 1. Refine
            refined = ingester._refine_content(raw)
            
            # 2. Fragment if needed
            fragments = ingester._segment_ideas(refined) if len(refined) > 1500 else []
            
            # Update main node
            updates = {
                "refined_content": refined,
                "type": "monolith_parent" if fragments else payload.get("type", "chronicle_node"),
                "fragment_count": len(fragments) if fragments else 0
            }
            mem.client.set_payload(collection_name=collection, payload=updates, points=[p.id])
            
            # Add child fragments
            for f_idx, frag in enumerate(fragments):
                f_id_seed = f"{p.id}_frag_{f_idx}"
                f_node_id = hashlib.sha256(f_id_seed.encode()).hexdigest()
                f_node_id = str(uuid.UUID(f_node_id[:32]))
                
                f_payload = {
                    "raw_content": frag["content"],
                    "refined_content": frag["content"],
                    "parent_id": str(p.id),
                    "session_id": payload.get("session_id"),
                    "type": "idea_fragment",
                    "associations": [{"id": str(p.id), "weight": 2.0}]
                }
                mem.add_memory(
                    collection=collection,
                    text=frag["content"],
                    point_id=f_node_id,
                    metadata=f_payload,
                    importance=3.0
                )
            
            total_refined += 1
            if total_refined % 100 == 0:
                logger.info(f"Refined {total_refined} nodes...")

        offset = next_offset
        if not offset:
            break

    logger.info(f"Cognitive Refinement complete. Total nodes processed: {total_refined}")

if __name__ == "__main__":
    main()
