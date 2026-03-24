#!/usr/bin/env python3
"""
chronicle_explorer.py — Navigate the Atomized Chronicle.

Usage:
  python chronicle_explorer.py "search query"
  python chronicle_explorer.py --thread <point_id>
"""

import argparse
import logging
from typing import List, Optional
from red_pill.memory import MemoryManager
from qdrant_client import models

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("chronicle_explorer")

class ChronicleExplorer:
    def __init__(self):
        self.mem = MemoryManager()
        self.collection = "archive_memories"

    def search(self, query: str, limit: int = 5):
        logger.info(f"--- Searching Chronicle for: '{query}' ---")
        results = self.mem.search_and_reinforce(collection=self.collection, query=query, limit=limit)
        
        for i, hit in enumerate(results):
            payload = hit.payload or {}
            print(f"[{i+1}] Score: {hit.score:.4f} | ID: {hit.id}")
            print(f"    Role: {payload.get('role', 'unknown')} | Session: {payload.get('session_id', 'N/A')}")
            print(f"    Content: {payload.get('raw_content', hit.payload.get('content', ''))[:200]}...")
            print(f"    Axons: {len(payload.get('associations', []))}")
            print("-" * 40)

    def traverse_thread(self, start_id: str, depth: int = 10):
        logger.info(f"--- Traversing Ariadne's Thread from: {start_id} ---")
        current_id = start_id
        visited = set()
        
        for _ in range(depth):
            if current_id in visited:
                break
            visited.add(current_id)
            
            try:
                points = self.mem.client.retrieve(
                    collection_name=self.collection,
                    ids=[current_id],
                    with_payload=True
                )
                if not points:
                    logger.warning(f"Point {current_id} not found.")
                    break
                
                p = points[0]
                payload = p.payload or {}
                role = payload.get('role', '???').upper()
                content = payload.get('raw_content', '')
                
                print(f"\n[{role}] ({current_id})")
                print(content)
                print("-" * 20)
                
                # Find the next sequential node
                # Our ingestion stores associations. In Ariadne's Thread, 
                # we usually have 1 backward and 1 forward link.
                # Heuristic: Find a link that hasn't been visited yet.
                assocs = payload.get("associations", [])
                next_id = None
                for assoc in assocs:
                    # Assoc can be a string ID or a dict {"id": ..., "weight": ...}
                    aid = assoc if isinstance(assoc, str) else assoc.get("id")
                    if aid and aid not in visited:
                        next_id = aid
                        break
                
                if not next_id:
                    logger.info("End of thread reached.")
                    break
                current_id = next_id
                
            except Exception as e:
                logger.error(f"Traversal failed: {e}")
                break

def main():
    parser = argparse.ArgumentParser(description="Explore the Atomized Chronicle.")
    parser.add_argument("query", type=str, nargs="?", help="Semantic search query.")
    parser.add_argument("--thread", type=str, help="Point ID to start thread traversal.")
    parser.add_argument("--limit", type=int, default=5, help="Search limit.")
    parser.add_argument("--depth", type=int, default=10, help="Thread traversal depth.")
    args = parser.parse_args()

    explorer = ChronicleExplorer()
    
    if args.thread:
        explorer.traverse_thread(args.thread, depth=args.depth)
    elif args.query:
        explorer.search(args.query, limit=args.limit)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
