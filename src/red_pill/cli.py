import sys
import argparse
import logging
import yaml
import os
from red_pill.memory import MemoryManager
from red_pill.seed import seed_project
from red_pill.config import LOG_LEVEL

def main():
    parser = argparse.ArgumentParser(description="Red Pill Protocol CLI - Memory Persistence Layer")
    parser.add_argument("--url", help="Qdrant URL (defaults to localhost:6333)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Mode command
    mode_parser = subparsers.add_parser("mode", help="Switch Lore Skin (Operational Mode)")
    mode_parser.add_argument("skin", help="Skin name (matrix, cyberpunk, 760, dune)")

    # Seed command
    subparsers.add_parser("seed", help="Initialize collections and seed genesis memories")

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
    log_level = logging.DEBUG if args.verbose else getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    
    manager = MemoryManager(url=args.url) if args.url else MemoryManager()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "mode":
        # Load lore skins
        data_path = os.path.join(os.path.dirname(__file__), "data", "lore_skins.yaml")
        try:
            with open(data_path, 'r') as f:
                skins = yaml.safe_load(f).get('modes', {})
        except Exception as e:
            logger.error(f"Could not load lore skins: {e}")
            sys.exit(1)

        if args.skin not in skins:
            print(f"Skin '{args.skin}' not found. Available: {', '.join(skins.keys())}")
            sys.exit(1)

        skin = skins[args.skin]
        print(f"--- Operational Mode: {args.skin.upper()} ---")
        for key, value in skin.items():
            print(f"{key.capitalize().replace('_', ' ')}: {value}")
        
        # In a real scenario, this would update a local state or .agent/rules
        print("\n[Protocol] Soul mapping updated. Re-calibrating identity anchor...")
        return

    if args.command == "seed":
        seed_project(manager)
        return # Exit after seed command as it doesn't require 'type'

    # For commands that require 'type'
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
