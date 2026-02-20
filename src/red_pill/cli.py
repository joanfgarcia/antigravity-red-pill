import argparse
import logging
import os
import signal
import sys

import yaml

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.seed import seed_project

logger = logging.getLogger(__name__)

def main() -> None:
	parser = argparse.ArgumentParser(description="Red Pill Protocol CLI")
	parser.add_argument("--url", help="Qdrant URL")
	parser.add_argument("--verbose", action="store_true", help="Debug logs")

	subparsers = parser.add_subparsers(dest="command")

	mode_parser = subparsers.add_parser("mode", help="Switch Lore Skin")
	mode_parser.add_argument("skin", help="matrix, cyberpunk, 760, dune")

	subparsers.add_parser("seed", help="Initialize memory substrate")

	add_parser = subparsers.add_parser("add", help="Add engram")
	add_parser.add_argument("type", choices=["work", "social"])
	add_parser.add_argument("content")
	add_parser.add_argument("--color", choices=["orange", "yellow", "purple", "cyan", "blue", "gray"], default=cfg.DEFAULT_COLOR)
	add_parser.add_argument("--emotion", choices=["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"], default=cfg.DEFAULT_EMOTION)
	add_parser.add_argument("--intensity", type=float, default=1.0)

	search_parser = subparsers.add_parser("search", help="Search and reinforce")
	search_parser.add_argument("type", choices=["work", "social"])
	search_parser.add_argument("query")
	search_parser.add_argument("--limit", type=int, default=3)
	search_parser.add_argument("--deep", action="store_true", help="Deep Recall bypass")

	erode_parser = subparsers.add_parser("erode", help="B760 erosion")
	erode_parser.add_argument("type", choices=["work", "social"])
	erode_parser.add_argument("--rate", type=float)

	subparsers.add_parser("diag", help="Diagnostics")
	subparsers.add_parser("daemon", help="Memory Sidecar")

	sanitize_parser = subparsers.add_parser("sanitize", help="Sanitation & Migration Protocol")
	sanitize_parser.add_argument("type", choices=["work", "social"])
	sanitize_parser.add_argument("--dry-run", action="store_true", help="Report without changes")

	args = parser.parse_args()

	log_level = logging.DEBUG if args.verbose else getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
	logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

	if not args.command:
		parser.print_help()
		sys.exit(0)

	if args.command == "daemon":
		try:
			from red_pill.memory_daemon import MemoryDaemon
			print("\n--- Despertando Sidecar de Memoria ---")
			daemon = MemoryDaemon()

			def stop_daemon(sig, frame):
				daemon.stop()
				sys.exit(0)

			signal.signal(signal.SIGINT, stop_daemon)
			signal.signal(signal.SIGTERM, stop_daemon)
			daemon.start()
		except Exception as e:
			logger.error(f"Daemon failure: {e}")
			sys.exit(1)
		return

	if args.command == "mode":
		data_path = os.path.join(os.path.dirname(__file__), "data", "lore_skins.yaml")
		try:
			with open(data_path, 'r') as f:
				raw_skins = yaml.safe_load(f).get('modes', {})
				skins = {str(k): v for k, v in raw_skins.items()}
		except Exception as e:
			logger.error(f"Lore load failed: {e}")
			sys.exit(1)

		if args.skin not in skins:
			sys.exit(1)

		skin = skins[args.skin]
		print(f"--- Operational Mode: {args.skin.upper()} ---")
		for key, value in skin.items():
			print(f"{key.capitalize().replace('_', ' ')}: {value}")
		return

	if args.command == "seed":
		manager = MemoryManager(url=args.url) if args.url else MemoryManager()
		seed_project(manager)
		return

	collection = "social_memories" if args.type == "social" else "work_memories"

	try:
		manager = MemoryManager(url=args.url) if args.url else MemoryManager()
		if args.command == "add":
			manager.add_memory(collection, args.content, color=args.color, emotion=args.emotion, intensity=args.intensity)
		elif args.command == "search":
			deep_trigger = any(phrase in args.query.lower() for phrase in cfg.DEEP_RECALL_TRIGGERS)
			is_deep = args.deep or deep_trigger

			results = manager.search_and_reinforce(collection, args.query, limit=args.limit, deep_recall=is_deep)
			if is_deep:
				print("--- [DEEP RECALL ACTIVATED] ---")
			for hit in results:
				score = hit.payload.get("reinforcement_score", 0.0)
				color = hit.payload.get("color", "gray")
				intensity = hit.payload.get("intensity", 1.0)
				status = " [IMMUNE]" if hit.payload.get("immune") else f" (Score: {score})"
				assocs = len(hit.payload.get("associations", []))

				print(f"- [{color.upper()}][Int: {intensity}] {hit.payload['content']}{status}")
				if assocs > 20:
					logger.warning(f"Synaptic Hub Detected: Engram {hit.id} has {assocs} associations (Limit: 20). Operations may lag.")
		elif args.command == "erode":
			manager.apply_erosion(collection, rate=args.rate) if args.rate else manager.apply_erosion(collection)
		elif args.command == "sanitize":
			results = manager.sanitize(collection, dry_run=args.dry_run)
			print("--- [SANITATION PROTOCOL COMPLETE] ---")
			print(f"Collection: {results['collection']}")
			print(f"Duplicates Removed: {results['duplicates_found']}")
			print(f"Records Migrated: {results['migrated_records']}")
			if args.dry_run:
				print("Note: DRY RUN - No changes applied.")
		elif args.command == "diag":
			stats = manager.get_stats(collection)
			for key, value in stats.items():
				print(f"{key.capitalize().replace('_', ' ')}: {value}")
	except Exception as e:
		logger.error(f"Protocol Failure: {e}")
		sys.exit(1)

if __name__ == "__main__":
	main()
