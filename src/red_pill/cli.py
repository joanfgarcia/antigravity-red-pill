import argparse
import logging
import os
import signal
import sys

import yaml  # type: ignore

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.seed import seed_project
from red_pill.soul import SoulManager
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import get_telemetry_report

logger = logging.getLogger(__name__)


def handle_mode(args: argparse.Namespace) -> None:
	"""Switch Lore Skin."""
	data_path = os.path.join(os.path.dirname(__file__), "data", "lore_skins.yaml")
	try:
		with open(data_path, "r") as f:
			raw_skins = yaml.safe_load(f).get("modes", {})
			skins = {str(k): v for k, v in raw_skins.items()}
	except Exception as e:
		logger.error(f"Lore load failed: {e}")
		sys.exit(1)

	if args.skin not in skins:
		logger.error(f"Invalid mode '{args.skin}'. Valid options: {', '.join(skins.keys())}")
		sys.exit(1)

	skin = skins[args.skin]
	print(f"--- Operational Mode: {args.skin.upper()} ---")
	for key, value in skin.items():
		print(f"{key.capitalize().replace('_', ' ')}: {value}")


def handle_daemon() -> None:
	"""Memory Sidecar."""
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


def get_collection(type_str: str) -> str:
	"""Map CLI type to collection name."""
	mapping = {
		"social": "social_memories",
		"work": "work_memories",
		"story": "story_memories",
		"directive": "directive_memories",
	}
	return mapping.get(type_str, "directive_memories")


def main() -> None:
	parser = argparse.ArgumentParser(description="Red Pill Protocol CLI")
	parser.add_argument("--url", help="Qdrant URL")
	parser.add_argument("--verbose", action="store_true", help="Debug logs")

	subparsers = parser.add_subparsers(dest="command")

	mode_parser = subparsers.add_parser("mode", help="Switch Lore Skin")
	mode_parser.add_argument("skin", help="matrix, cyberpunk, 760, dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator")

	subparsers.add_parser("seed", help="Initialize memory substrate")

	add_parser = subparsers.add_parser("add", help="Add engram")
	add_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	add_parser.add_argument("content")
	add_parser.add_argument("--color", choices=["orange", "yellow", "purple", "cyan", "blue", "gray"], default=cfg.DEFAULT_COLOR)
	add_parser.add_argument(
		"--emotion",
		choices=["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"],
		default=cfg.DEFAULT_EMOTION,
	)
	add_parser.add_argument("--intensity", type=float, default=1.0)

	search_parser = subparsers.add_parser("search", help="Search and reinforce")
	search_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	search_parser.add_argument("query")
	search_parser.add_argument("--limit", type=int, default=3)
	search_parser.add_argument("--deep", action="store_true", help="Deep Recall bypass")

	erode_parser = subparsers.add_parser("erode", help="B760 erosion")
	erode_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	erode_parser.add_argument("--rate", type=float)

	diag_parser = subparsers.add_parser("diag", help="Diagnostics")
	diag_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	subparsers.add_parser("daemon", help="Memory Sidecar")

	sanitize_parser = subparsers.add_parser("sanitize", help="Sanitation & Migration Protocol")
	sanitize_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	sanitize_parser.add_argument("--dry-run", action="store_true", help="Report without changes")

	subparsers.add_parser("status", help="Hardware Control Panel")

	swarm_parser = subparsers.add_parser("swarm", help="Sovereign Swarm Operations")
	swarm_sub = swarm_parser.add_subparsers(dest="swarm_cmd")
	audit_parser = swarm_sub.add_parser("audit", help="Launch Agent Smith Code Audit")
	audit_parser.add_argument("--path", default=".", help="Target path for audit")

	soul_parser = subparsers.add_parser("soul", help="B760 Soul Management")
	soul_sub = soul_parser.add_subparsers(dest="soul_cmd")
	soul_sub.add_parser("backup", help="Execute total soul backup (Qdrant + Files)")
	soul_sub.add_parser("export", help="Package soul into a portable kit")
	restore_parser = soul_sub.add_parser("restore", help="Restore soul from a backup directory")
	restore_parser.add_argument("source", help="Path to backup timestamp directory")
	restore_parser.add_argument("--commit", action="store_true", help="Execute the restoration (dry-run by default)")

	args = parser.parse_args()

	log_level = logging.DEBUG if args.verbose else getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
	logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

	if not args.command:
		parser.print_help()
		sys.exit(0)

	if args.command == "daemon":
		handle_daemon()
		return
	elif args.command == "mode":
		handle_mode(args)
		return

	# Map CLI type to collection(s)
	if getattr(args, "type", None):
		collections = [get_collection(args.type)]
	elif args.command in ["seed", "status", "swarm", "soul"]:
		collections = [] # Not needed for these
	else:
		# Default sweep for search/diag if no type specified
		collections = ["work_memories", "social_memories"]

	try:
		manager = MemoryManager(url=args.url) if args.url else MemoryManager()

		if args.command == "seed":
			seed_project(manager)
			return
		elif args.command == "status":
			print(get_telemetry_report())
			return
		elif args.command == "swarm":
			if args.swarm_cmd == "audit":
				import asyncio
				gru = GruOrchestrator()
				smith = SmithMinion()
				print(f"--- [DEPLOING SWARM: AGENT {smith.name.upper()}] ---")
				results = asyncio.run(gru.deploy_swarm("audit", [smith], path=args.path))
				for res in results:
					if res.status == "success":
						print(f"\nResultados de {res.minion_id[:8]}:")
						print(f"- Score de Seguridad: {res.result['security_score']}/100")
						print(f"- Archivos escaneados: {res.result['files_scanned']}")
						print(f"- Hallazgos Críticos: {len([f for f in res.result['findings'] if f['severity'] == 'CRITICAL'])}")
						if res.result['findings']:
							print("\n--- HALLAZGOS ---")
							for finding in res.result['findings'][:5]:
								print(f"[{finding['severity']}] {finding['file']}:{finding['line']} - {finding['msg']}")
					else:
						print(f"ERROR en Minion {res.minion_id}: {res.error}")
			return
		elif args.command == "soul":
			soul = SoulManager()
			if args.soul_cmd == "backup":
				soul.full_backup()
			elif args.soul_cmd == "export":
				soul.export_soul()
			elif args.soul_cmd == "restore":
				soul.restore_soul(args.source, commit=args.commit)
			return

		# Loop through requested collections
		for collection in collections:
			if args.command == "add":
				manager.add_memory(collection, args.content, color=args.color, emotion=args.emotion, intensity=args.intensity)
			elif args.command == "search":
				deep_trigger = any(phrase in args.query.lower() for phrase in cfg.DEEP_RECALL_TRIGGERS)
				is_deep = args.deep or deep_trigger

				results = manager.search_and_reinforce(collection, args.query, limit=args.limit, deep_recall=is_deep)
				if is_deep:
					print(f"--- [DEEP RECALL ACTIVATED: {collection.upper()}] ---")
				else:
					print(f"--- [RESULTS: {collection.upper()}] ---")

				for hit in results:
					score = hit.payload.get("reinforcement_score", 0.0)
					color = hit.payload.get("color", "gray")
					intensity = hit.payload.get("intensity", 1.0)
					status = " [IMMUNE]" if hit.payload.get("immune") else f" (Score: {score:.2f})"
					assocs_val = hit.payload.get("associations")
					assocs = len(assocs_val) if assocs_val is not None else 0

					print(f"- [{color.upper()}][Int: {intensity}] {hit.payload['content']}{status}")
					if assocs > 20:
						logger.warning(f"Synaptic Hub Detected: Engram {hit.id} has {assocs} associations (Limit: 20). Operations may lag.")
			elif args.command == "erode":
				rate = args.rate if args.rate else None
				manager.apply_erosion(collection, rate=rate)
				print(f"Erosion applied to {collection}.")
			elif args.command == "sanitize":
				san_results = manager.sanitize(collection, dry_run=args.dry_run)
				print(f"--- [SANITATION: {collection.upper()}] ---")
				print(f"Duplicates Removed: {san_results['duplicates_found']}")
				print(f"Records Migrated: {san_results['migrated_records']}")
				if args.dry_run and (san_results["duplicates_found"] > 0 or san_results["migrated_records"] > 0):
					print("Note: DRY RUN - No changes applied.")
			elif args.command == "diag":
				print(f"--- [DIAGNOSTICS: {collection.upper()}] ---")
				stats = manager.get_stats(collection)
				for key, value in stats.items():
					print(f"{key.capitalize().replace('_', ' ')}: {value}")

	except Exception as e:
		logger.error(f"Protocol Failure: {e}")
		sys.exit(1)


if __name__ == "__main__":
	main()
