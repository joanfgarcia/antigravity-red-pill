import sys
import argparse
import logging
from red_pill.memory import MemoryManager

def main():
    parser = argparse.ArgumentParser(description="Red Pill Protocol CLI - Memory Persistence Layer")
    parser.add_argument("--url", help="Qdrant URL (defaults to localhost:6333)")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new memory engram")
    add_parser.add_argument("type", choices=["work", "social"], help="Collection type")
    add_parser.add_argument("content", help="Memory text to store")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search and reinforce memories")
    search_parser.add_argument("type", choices=["work", "social"], help="Collection type")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=3, help="Max results")

    # Erode command
    erode_parser = subparsers.add_parser("erode", help="Apply B760 erosion cycle")
    erode_parser.add_argument("type", choices=["work", "social"], help="Collection type")
    erode_parser.add_argument("--rate", type=float, help="Custom erosion rate")

    # Diag command
    diag_parser = subparsers.add_parser("diag", help="Collection diagnostics")
    diag_parser.add_argument("type", choices=["work", "social"], help="Collection type")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    manager = MemoryManager(url=args.url) if args.url else MemoryManager()
    collection = "social_memories" if args.type == "social" else "work_memories"

    if args.command == "add":
        manager.add_memory(collection, args.content)
    elif args.command == "search":
        results = manager.search_and_reinforce(collection, args.query, limit=args.limit)
        for i, hit in enumerate(results):
            score = hit.payload.get('reinforcement_score', 0)
            immune = hit.payload.get('immune', False)
            status = "[IMMUNE]" if immune else f"[B760: {score:.2f}]"
            print(f"[{i}] {status} | Similarity: {hit.score:.4f}")
            print(f"Content: {hit.payload.get('content')}\n")
    elif args.command == "erode":
        manager.apply_erosion(collection, rate=args.rate) if args.rate else manager.apply_erosion(collection)
    elif args.command == "diag":
        stats = manager.get_stats(collection)
        print(f"--- Diagnostics: {collection} ---")
        for key, value in stats.items():
            print(f"{key.capitalize().replace('_', ' ')}: {value}")

if __name__ == "__main__":
    main()
