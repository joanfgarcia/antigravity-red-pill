import argparse
import asyncio
import importlib.metadata
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List

import yaml  # type: ignore

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.seed import ID_DIR_ACTIVE_SKIN, seed_project
from red_pill.soul import SoulManager
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.base import SwarmResult
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import get_telemetry_report
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

# v6.0.1: Robust Script Resolution
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def switch_skin(skin_name: str) -> str:
	"""Switch Lore Skin and persist in Bünker."""
	data_path = os.path.join(os.path.dirname(__file__), "data", "lore_skins.yaml")
	try:
		with open(data_path, "r") as f:
			raw_skins = yaml.safe_load(f).get("modes", {})
			skins = {str(k): v for k, v in raw_skins.items()}
	except Exception as e:
		return f"Lore load failed: {e}"

	if skin_name not in skins:
		return f"Invalid mode '{skin_name}'. Valid options: {', '.join(skins.keys())}"

	skin = skins[skin_name]
	report = f"--- Operational Mode: {skin_name.upper()} ---\n"
	for key, value in skin.items():
		report += f"{key.capitalize().replace('_', ' ')}: {value}\n"

	# Persist Active Skin in Directives (v6.1.0: Singleton Upsert)
	try:
		manager = MemoryManager()
		content = f"Active Skin: {skin_name.upper()}\n{yaml.dump(skin)}"
		manager.add_memory(
			collection="directive_memories",
			text=content,
			importance=10.0,
			metadata={"type": "active_skin", "skin_name": skin_name},
			color=skin.get("chroma", "gray"),
			force_immune=True,
			point_id=ID_DIR_ACTIVE_SKIN,
		)
		return report + f"\n[OK] Skin '{skin_name}' synchronized with Sovereign Directives."
	except Exception as e:
		return report + f"\n[ERROR] Failed to persist active skin: {e}"


def handle_mode(args: argparse.Namespace) -> None:
	"""CLI wrapper for skin switching (with SEC-007 explicit consent)."""
	neutral_skins = ["pioneer", "academic"]
	if args.skin not in neutral_skins and not getattr(args, "yes", False):
		print("\n--- [SEC-007 CONSENT REQUIRED] ---")
		print(f"Warning: Skin '{args.skin.upper()}' modifies base AI neutrality and behavioral filters.")
		print("For exact behavioral modifiers, see 'src/red_pill/data/lore_skins.yaml'")
		print("By proceeding, you assume sovereignty over the agent's altered psychological posture.")
		confirm = input("Type 'Y' to confirm and bypass safety protocols: ")
		if confirm.strip().upper() != "Y":
			print("Skin application aborted. Safety protocols maintained.")
			return
	print(switch_skin(args.skin))


def handle_audit() -> None:
	"""Pre-PR Audit Protocol."""
	script_path = os.path.join(PROJECT_ROOT, "scripts", "pre_pr_audit.sh")
	print(f"--- [DEPLOYING AUDIT PROTOCOL: {script_path}] ---")
	try:
		subprocess.run(["bash", script_path], check=True)
	except subprocess.CalledProcessError:
		sys.exit(1)


def handle_heal(dry_run: bool = False) -> None:
	"""Samantha's Local Healing Cycle."""
	script_path = os.path.join(PROJECT_ROOT, "scripts", "local_healer.py")
	cmd = [sys.executable, script_path]
	if dry_run:
		cmd.append("--dry-run")
	print(f"--- [DEPLOYING HEALER: {script_path}] ---")
	try:
		subprocess.run(cmd, check=True)
	except subprocess.CalledProcessError:
		sys.exit(1)


def handle_benchmark() -> None:
	"""Sovereignty Benchmark (Tri-Tier Hardware)."""
	script_path = os.path.join(PROJECT_ROOT, "scripts", "sovereignty_benchmark.py")
	print(f"--- [DEPLOYING BENCHMARK: {script_path}] ---")
	subprocess.run([sys.executable, script_path])


def handle_identity(args: argparse.Namespace) -> None:
	"""Identity Management (Bootstrap/Refresh)."""
	if args.id_cmd == "bootstrap":
		script_path = os.path.join(PROJECT_ROOT, "scripts", "bootstrap_identity.py")
		cmd = [sys.executable, script_path]
		if args.ai_name:
			cmd.extend(["--ai-name", args.ai_name])
		if args.ai_role:
			cmd.extend(["--ai-role", args.ai_role])
		if args.user_name:
			cmd.extend(["--user-name", args.user_name])
		if args.user_role:
			cmd.extend(["--user-role", args.user_role])
		if args.skin:
			cmd.extend(["--skin", args.skin])
		subprocess.run(cmd)
	elif args.id_cmd == "refresh":
		script_path = os.path.join(PROJECT_ROOT, "scripts", "wake_up_v6.py")
		print(f"--- [REFRESHING SESSION CONTEXT: {script_path}] ---")
		subprocess.run([sys.executable, script_path])
	elif args.id_cmd == "purge":
		print("--- [WARNING: INITIATING GDPR PURGE] ---")
		print("This will destroy all memories, directives, and identity context forever.")
		confirm = input("Type 'PURGE' to confirm: ")
		if confirm == "PURGE":
			from red_pill.memory import MemoryManager

			mgr = MemoryManager()
			mgr.purge_identity()
			print("[OK] Identity and collections purged. System is a blank slate.")
		else:
			print("Purge aborted.")


def get_collection(type_str: str) -> str:
	"""Map CLI type to collection name."""
	mapping = {
		"social": "social_memories",
		"work": "work_memories",
		"story": "story_memories",
		"directive": "directive_memories",
	}
	return mapping.get(type_str, "directive_memories")


# ---------------------------------------------------------------------------
# CLI Plugin Discovery (EntryPoints)
# ---------------------------------------------------------------------------
# Enterprise/Community packages declare their commands in pyproject.toml:
#
#   [project.entry-points."red_pill.commands"]
#   cerberus = "red_pill_enterprise.cli:CerberusPlugin"
#
# Each plugin class must implement:
#   - register(subparsers: argparse._SubParsersAction) -> None
#       Add your subparser(s) to the Foundation's main subparsers object.
#   - handle(args: argparse.Namespace) -> bool
#       Handle the command. Return True if handled, False to pass through.
# ---------------------------------------------------------------------------

_PLUGIN_REGISTRY: Dict[str, Any] = {}


def load_plugins(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
	"""
	Discover and register CLI plugins via 'red_pill.commands' EntryPoints.
	Called once before argparse.parse_args(), so plugins can add subcommands.
	"""
	try:
		eps = importlib.metadata.entry_points(group="red_pill.commands")
		for ep in eps:
			try:
				plugin_cls = ep.load()
				plugin = plugin_cls()
				plugin.register(subparsers)
				_PLUGIN_REGISTRY[ep.name] = plugin
				logger.debug(f"[CLI] Loaded plugin: {ep.name} ({ep.value})")
			except Exception as e:
				logger.warning(f"[CLI] Failed to load plugin '{ep.name}': {e}")
	except Exception as e:
		logger.debug(f"[CLI] EntryPoints discovery skipped: {e}")


def _dispatch_plugins(args: argparse.Namespace) -> bool:
	"""
	Try each registered plugin's handle() method.
	Returns True if a plugin handled the command (stops dispatch chain).
	"""
	for name, plugin in _PLUGIN_REGISTRY.items():
		try:
			if plugin.handle(args):
				return True
		except Exception as e:
			logger.warning(f"[CLI] Plugin '{name}' raised an exception: {e}")
	return False


def main() -> None:
	parser = argparse.ArgumentParser(description="Red Pill Protocol CLI")
	parser.add_argument("--url", help="Qdrant URL")
	parser.add_argument("--verbose", action="store_true", help="Debug logs")

	subparsers = parser.add_subparsers(dest="command")

	# Load Enterprise / Community plugins BEFORE Foundation commands so they
	# can extend (or wrap) any subparser group.
	load_plugins(subparsers)

	mode_parser = subparsers.add_parser("mode", help="Switch Lore Skin")
	mode_parser.add_argument("skin", help="matrix, cyberpunk, 760, dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator")
	mode_parser.add_argument("--yes", "--force", action="store_true", help="Bypass SEC-007 consent prompt")

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

	sanitize_parser = subparsers.add_parser("sanitize", help="Sanitation & Migration Protocol")
	sanitize_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	sanitize_parser.add_argument("--dry-run", action="store_true", help="Report without changes")
	sanitize_parser.add_argument("--raw", action="store_true", help="Bypass Pydantic validation (Raw Read maintenance fallback)")

	subparsers.add_parser("status", help="Hardware Control Panel")

	swarm_parser = subparsers.add_parser("swarm", help="Sovereign Swarm Operations")
	swarm_sub = swarm_parser.add_subparsers(dest="swarm_cmd")

	sleep_parser = subparsers.add_parser("sleep", help="Lazarus Maintenance Ritual")
	sleep_parser.add_argument("--mode", choices=["lazy", "deep"], default="lazy", help="Deep mode forces full pruning")
	audit_parser = swarm_sub.add_parser("audit", help="Launch Agent Smith Code Audit")
	audit_parser.add_argument("--path", default=".", help="Target path for audit")

	backup_parser = subparsers.add_parser("backup", help="Create fast Qdrant snapshots (Pre-Migration Safety)")
	backup_parser.add_argument("--collections", nargs="+", help="Specific collections to backup")

	soul_parser = subparsers.add_parser("soul", help="B760 Soul Management")
	soul_sub = soul_parser.add_subparsers(dest="soul_cmd")
	soul_sub.add_parser("backup", help="Execute total soul backup (Qdrant + Files)")
	soul_sub.add_parser("export", help="Package soul into a portable kit")
	soul_sub.add_parser("rotate", help="Rotate Qdrant API Key and restart service")
	restore_parser = soul_sub.add_parser("restore", help="Restore soul from a backup directory")
	restore_parser.add_argument("source", help="Path to backup source")
	restore_parser.add_argument("--commit", action="store_true", help="Execute the restoration")
	verify_parser = soul_sub.add_parser("verify", help="Verify backup integrity without restoring")
	verify_parser.add_argument("source", help="Path to backup kit (.tar.gz or .enc)")
	soul_sub.add_parser("sync", help="Check emotional sync state")
	soul_sub.add_parser("vault", help="Inspect Cloud Vault status and backups")

	edit_parser = subparsers.add_parser("edit", help="Edit engram attributes")
	edit_parser.add_argument("type", choices=["work", "social", "directive", "story"])
	edit_parser.add_argument("id", help="The UUID of the engram to edit")
	edit_parser.add_argument("--color", choices=["orange", "yellow", "purple", "cyan", "blue", "gray"])
	edit_parser.add_argument(
		"--emotion",
		choices=["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"],
	)
	edit_parser.add_argument("--intensity", type=float)

	signal_parser = subparsers.add_parser("signal", help="Sovereign Alert System (SAS) trigger")
	signal_parser.add_argument("message", help="Notification message")
	signal_parser.add_argument("--title", default="Red Pill: Task Complete", help="Notification title")
	signal_parser.add_argument("--sound", action="store_true", help="Enable sensory pulse (sound)")
	signal_parser.add_argument("--silent", action="store_true", help="Do not send desktop notification (Memory only)")

	init_parser = subparsers.add_parser("init", help="Bootstrap a Spec-Compliant project")
	init_parser.add_argument("--flow", choices=["fire", "simple", "aidlc"], default="fire", help="Initial specs.md flow")

	subparsers.add_parser("audit", help="Run Pre-PR Audit (Ruff, Mypy, Pytest)")

	heal_parser = subparsers.add_parser("heal", help="Run Samantha Local Healer (Auto-fix Mypy)")
	heal_parser.add_argument("--dry-run", action="store_true")

	subparsers.add_parser("benchmark", help="Run Sovereignty Benchmark (Hardware Concurrency)")

	id_parser = subparsers.add_parser("identity", help="Identity & Persona Management")
	id_sub = id_parser.add_subparsers(dest="id_cmd")

	boot_parser = id_sub.add_parser("bootstrap", help="Initialize Sovereign Identity")
	boot_parser.add_argument("--ai-name")
	boot_parser.add_argument("--ai-role")
	boot_parser.add_argument("--user-name")
	boot_parser.add_argument("--user-role")
	boot_parser.add_argument("--skin")

	id_sub.add_parser("refresh", help="Synthesize and refresh session context (wake_up)")
	id_sub.add_parser("purge", help="GDPR Art 17: Right to be Forgotten. Destroys all memory collections and local identity.")

	args = parser.parse_args()

	log_level = logging.DEBUG if args.verbose else getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)

	if os.getenv("LOG_JSON", "False").lower() == "true":
		import json

		class JsonFormatter(logging.Formatter):
			def format(self, record):
				log_record = {
					"timestamp": self.formatTime(record, self.datefmt),
					"level": record.levelname,
					"name": record.name,
					"message": record.getMessage(),
				}
				if record.exc_info:
					log_record["exception"] = self.formatException(record.exc_info)
				return json.dumps(log_record)

		handler = logging.StreamHandler()
		handler.setFormatter(JsonFormatter())
		logging.basicConfig(level=log_level, handlers=[handler])  # type: ignore
	else:
		logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

	# SEC-F04: Prevención de fuga de credenciales en logs
	class SecretMasker(logging.Filter):
		def filter(self, record):
			try:
				msg = str(record.msg)
				secrets = [cfg.QDRANT_API_KEY, getattr(cfg, "SIDECAR_AUTH_KEY", ""), getattr(cfg, "MILVUS_PASSWORD", "")]
				for secret in secrets:
					if secret and isinstance(secret, str) and len(secret) > 4:
						msg = msg.replace(secret, f"***{secret[-4:]}")
				record.msg = msg
			except Exception:
				pass
			return True

	for h in logging.root.handlers:
		h.addFilter(SecretMasker())

	if not args.command:
		parser.print_help()
		sys.exit(0)

	elif args.command == "mode":
		handle_mode(args)
		return

	# Map CLI type to collection(s)
	if getattr(args, "type", None):
		collections = [get_collection(args.type)]
	elif args.command in ["seed", "status", "swarm", "soul", "init"]:
		collections = []  # Not needed for these
	else:
		# Default sweep for search/diag if no type specified
		collections = ["work_memories", "social_memories"]

	try:
		manager = MemoryManager(url=args.url) if args.url else MemoryManager()

		# Telemetry initialization
		points_affected = 0

		if args.command == "seed":
			seed_project(manager)
			return
		elif args.command == "sleep":
			from red_pill.metabolism.sleep import perform_sleep_cycle

			print("\n[LAZARUS PULSE] Initiating Maintenance Ritual (Sleep Cycle)...")
			try:
				points_affected = perform_sleep_cycle(manager, mode=args.mode)  # Pass mode from args
				print(f"[OK] Ritual Complete. {points_affected} engrams consolidated via FSRS Fixation.")
			except Exception as e:
				print(f"[ERROR] Sleep cycle interrupted: {e}")
			return  # Added return here
		elif args.command == "backup":
			print("\n--- [BÜNKER BACKUP: CREATING LOCAL SNAPSHOTS] ---")
			results = manager.create_bunker_snapshot(collections=args.collections)
			for coll, snap in results.items():
				if snap.startswith("ERROR"):
					print(f"[FAIL] {coll}: {snap}")
				else:
					print(f"[OK] {coll}: {snap}")
			return
		elif args.command == "status":
			print(get_telemetry_report())
			return
		elif args.command == "swarm":
			if args.swarm_cmd == "audit":
				gru = GruOrchestrator()
				smith = SmithMinion()
				print(f"--- [DEPLOYING SWARM: AGENT {smith.name.upper()}] ---")
				# Explicitly type results for Mypy
				swarm_results: List[SwarmResult] = asyncio.run(gru.deploy_swarm("audit", [smith], path=args.path))
				for res in swarm_results:
					if res.status == "success":
						print(f"\nResultados de {res.minion_id[:8]}:")
						print(f"- Score de Seguridad: {res.result['security_score']}/100")
						print(f"- Archivos escaneados: {res.result['files_scanned']}")
						print(f"- Hallazgos Críticos: {len([f for f in res.result['findings'] if f['severity'] == 'CRITICAL'])}")
						if res.result["findings"]:
							print("\n--- HALLAZGOS ---")
							for finding in res.result["findings"][:5]:
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
			elif args.soul_cmd == "rotate":
				from scripts.rotate_keys import rotate

				rotate()
			elif args.soul_cmd == "restore":
				soul.restore_soul(args.source, commit=args.commit)
			elif args.soul_cmd == "verify":
				if soul.verify_soul(args.source):
					print(f"\n[OK] VERIFIED: {args.source} is healthy.")
				else:
					print(f"\n[FAIL] CORRUPT OR INVALID: {args.source}")
					sys.exit(1)
			elif args.soul_cmd == "sync":
				state = get_current_sync_state()
				print(f"--- [EMOTIONAL SYNC: {state['mood'].upper()}] ---")
				print(f"Directive: {state['directive']}")
			elif args.soul_cmd == "vault":
				if soul.vault.enabled:
					print("--- [CLOUD VAULT: ACTIVE (Google Drive)] ---")
					files = soul.vault.list_backups()
					if not files:
						print("Vault is empty. Run 'red-pill soul export' to transmit your first kit.")
					else:
						for f in files:
							print(f"- {f['name']} ({f['createdTime']}) [ID: {f['id']}]")
				else:
					print("--- [CLOUD VAULT: INACTIVE] ---")
					print(f"To enable, set CLOUD_VAULT_ENABLED=True in .env and provide {cfg.CLOUD_SERVICE_ACCOUNT_FILE}")
			return
		elif args.command == "init":
			import subprocess

			from red_pill.utils.observer import notify_user

			print(f"--- [INITIALIZING SPECS.MD FLOW: {args.flow.upper()}] ---")
			try:
				# 1. Initialize specs.md infrastructure (Notebook on disk)
				subprocess.run(["npx", "-y", "specsmd@latest", "install"], check=True)

				# 2. Notify Success (Bünker mapping removed)
				from red_pill import __version__

				print(f"\n[OK] Flow '{args.flow}' initialized on disk (Notebook mode).")
				notify_user("Project Initialized", f"Red Pill v{__version__} + specs.md {args.flow} flow is now live.", category="init")
			except Exception as e:
				print(f"[FAIL] Initialization failed: {e}")
			return
		elif args.command == "audit":
			handle_audit()
			return
		elif args.command == "heal":
			handle_heal(args.dry_run)
			return
		elif args.command == "benchmark":
			handle_benchmark()
			return
		elif args.command == "identity":
			handle_identity(args)
			return

		# Loop through requested collections
		for collection in collections:
			if args.command == "add":
				manager.add_memory(collection, args.content, color=args.color, emotion=args.emotion, intensity=args.intensity)
			elif args.command == "search":
				# CQ-003: Use regex with word boundaries for robust trigger detection
				import re as regex_lib

				is_deep = args.deep
				if not is_deep:
					for phrase in cfg.DEEP_RECALL_TRIGGERS:
						pattern = rf"\b{regex_lib.escape(phrase)}\b"
						if regex_lib.search(pattern, args.query, regex_lib.IGNORECASE):
							is_deep = True
							break

				search_results = manager.search_and_reinforce(collection, args.query, limit=args.limit, deep_recall=is_deep)
				if is_deep:
					print(f"--- [DEEP RECALL ACTIVATED: {collection.upper()}] ---")
				else:
					print(f"--- [RESULTS: {collection.upper()}] ---")

				for hit in search_results:
					score = getattr(hit, "payload", {}).get("reinforcement_score", 0.0)
					color = getattr(hit, "payload", {}).get("color", "gray")
					intensity = getattr(hit, "payload", {}).get("intensity", 1.0)
					status = " [IMMUNE]" if getattr(hit, "payload", {}).get("immune") else f" (Score: {score:.2f})"
					assocs_val = getattr(hit, "payload", {}).get("associations", [])
					assocs = len(assocs_val) if assocs_val is not None else 0

					payload = getattr(hit, "payload", {})
					content = payload.get("content", "")
					print(f"- [{color.upper()}][Int: {intensity}] {content}{status}")
					if assocs > 20:
						logger.warning(f"Synaptic Hub Detected: Engram {hit.id} has {assocs} associations (Limit: 20). Operations may lag.")
			elif args.command == "erode":
				rate = args.rate if args.rate else None
				manager.apply_erosion(collection, rate=rate)
				print(f"Erosion applied to {collection}.")
			elif args.command == "sanitize":
				san_results = manager.sanitize(collection, dry_run=args.dry_run, strict=not args.raw)
				print(f"--- [SANITATION: {collection.upper()}] ---")
				print(f"Duplicates Removed: {san_results['duplicates_found']}")
				print(f"Records Migrated: {san_results['migrated_records']}")
				print(f"Records Refracted: {san_results['refracted_records']}")
				if args.dry_run and (
					san_results["duplicates_found"] > 0 or san_results["migrated_records"] > 0 or san_results["refracted_records"] > 0
				):
					print("Note: DRY RUN - No changes applied.")
			elif args.command == "edit":
				success = manager.update_memory(collection, args.id, color=args.color, emotion=args.emotion, intensity=args.intensity)
				if success:
					print(f"[OK] Engram {args.id} updated in {collection}.")
				else:
					print(f"[FAIL] Could not update engram {args.id}.")
			elif args.command == "diag":
				print(f"--- [DIAGNOSTICS: {collection.upper()}] ---")
				stats = manager.get_stats(collection)
				for key, value in stats.items():
					print(f"{key.capitalize().replace('_', ' ')}: {value}")
			elif args.command == "signal":
				from red_pill.utils.observer import notify_user

				if not args.silent:
					notify_user(args.title, args.message, sound=args.sound, category="manual")

				# Record memory of the signal
				manager.add_memory(
					collection="directive_memories",
					text=f"SAS Signal: {args.title} - {args.message}",
					importance=1.0,
					metadata={"type": "sas_signal", "timestamp": time.time(), "message": args.message},
				)
				print(f"[SAS] Signal recorded: {args.message}")

			else:
				# --- Enterprise/Community Plugin Dispatch ---
				# If no built-in command matched, let plugins handle it.
				if not _dispatch_plugins(args):
					parser.print_help()
					sys.exit(1)

	except Exception as e:
		logger.error(f"Protocol Failure: {e}")
		sys.exit(1)


if __name__ == "__main__":
	main()
