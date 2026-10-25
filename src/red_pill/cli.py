import asyncio
import json
import logging
import os
import sys
from typing import List

import red_pill.config as cfg
from red_pill.cli_commands import (  # noqa: F401  (re-exported for `red_pill.cli.X` compat)
	_PLUGIN_REGISTRY,
	_dispatch_plugins,
	get_collection,
	handle_audit,
	handle_benchmark,
	handle_daemon,
	handle_heal,
	handle_interceptor,
	handle_mode,
	handle_pact,
	handle_telemetry,
	load_plugins,
	seal_pact,
	switch_skin,
)
from red_pill.cli_jobs import handle_job
from red_pill.cli_parser import build_parser
from red_pill.cli_services import (  # noqa: F401  (re-exported for `red_pill.cli.X` compat)
	handle_ide,
	handle_identity,
	handle_license,
	handle_mcp,
	handle_memory,
	handle_mini,
	handle_p2p,
	handle_runtime,
	handle_session,
	handle_telegram,
)
from red_pill.events import CliCommandDispatchedEvent, get_event_bus
from red_pill.memory import MemoryManager
from red_pill.seed import seed_project
from red_pill.soul import SoulManager
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.base import SwarmResult
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.telemetry import get_telemetry_report
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

# v6.0.1: Robust Script Resolution
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
	parser, config_parser = build_parser()
	args = parser.parse_args()

	log_level = logging.DEBUG if args.verbose else getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)

	if os.getenv("LOG_JSON", "False").lower() == "true":

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

	elif args.command == "daemon":
		handle_daemon()
		return

	elif args.command == "telemetry":
		handle_telemetry()
		return

	elif args.command == "mode":
		handle_mode(args)
		return

	elif args.command == "pact":
		handle_pact(args)
		return

	elif args.command == "session":
		handle_session(args)
		return

	elif args.command == "mcp":
		handle_mcp(args)
		return

	elif args.command == "mini":
		sys.exit(handle_mini(args))

	# EventBus: let Enterprise/Community know which command was dispatched
	get_event_bus().emit(
		CliCommandDispatchedEvent(
			command=args.command,
			subcommand=getattr(args, "swarm_cmd", None)
			or getattr(args, "soul_cmd", None)
			or getattr(args, "id_cmd", None)
			or getattr(args, "mem_cmd", None)
			or getattr(args, "config_cmd", None),
		)
	)

	# Map CLI type to collection(s)
	if getattr(args, "type", None):
		collections = [get_collection(args.type)]
	elif args.command in ["seed", "status", "swarm", "soul", "init", "bunker", "ide", "daemon", "memory", "config"]:
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
			from red_pill.core.providers import ProviderRegistry, SipInferenceProvider
			from red_pill.metabolism.sleep import perform_sleep_cycle

			ProviderRegistry.register_inference_provider("sip", SipInferenceProvider(socket_path=cfg.SIP_SOCKET_PATH))

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
		elif args.command == "cortex":
			from red_pill.telemetry import get_cortex_status

			status_dict = get_cortex_status()
			print(json.dumps(status_dict, indent=2))
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
			elif args.swarm_cmd == "broadcast":
				print("\n📢 --- [BROADCASTING SWARM MESSAGE] ---")
				print(f"Message: {args.message}")
				print(f"Channel: {args.channel}")

				from red_pill.core.paths import get_neon_link_db_path

				db_path = get_neon_link_db_path()

				payload_json = json.dumps({"text": args.message, "mode": "background", "priority": "normal", "group_size": 100})

				try:
					import sqlite3

					conn = sqlite3.connect(str(db_path))
					cursor = conn.cursor()
					cursor.execute(
						"INSERT INTO outbox (channel, channel_user_id, payload) VALUES (?, ?, ?)", (args.channel, "broadcast", payload_json)
					)
					conn.commit()
					conn.close()
					print("[OK] Broadcast message enqueued to neon-link outbox successfully.")
				except Exception as e:
					print(f"[ERROR] Failed to enqueue broadcast message: {e}")
			return
		elif args.command == "soul":
			soul = SoulManager()
			if args.soul_cmd == "backup":
				soul.full_backup()
			elif args.soul_cmd == "export":
				from red_pill.interceptors import _init_sovereign_plugins

				async def run_export():
					await _init_sovereign_plugins()
					await soul.export_soul()

				asyncio.run(run_export())
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
				if soul.vault.enabled:  # type: ignore
					print("--- [CLOUD VAULT: ACTIVE (Google Drive)] ---")
					files = soul.vault.list_backups()  # type: ignore
					if not files:
						print("Vault is empty. Run 'red-pill soul export' to transmit your first kit.")
					else:
						for f in files:
							print(f"- {f['name']} ({f['createdTime']}) [ID: {f['id']}]")
				else:
					print("--- [CLOUD VAULT: INACTIVE] ---")
					print("To enable Cloud Sync, configure the 'cloud_sync' plugin in <IA_DIR>/plugins/cloud_sync/cloud_sync.json")
			elif args.soul_cmd == "migrate":
				from red_pill.soul_migrate import run_migrate_cli

				migrate_args = sys.argv[sys.argv.index("migrate") + 1 :]
				run_migrate_cli(migrate_args)
			return
		elif args.command == "init":
			import subprocess

			from red_pill.core.notifier import SovereignNotifier

			print(f"--- [INITIALIZING SPECS.MD FLOW: {args.flow.upper()}] ---")
			try:
				# 1. Initialize specs.md infrastructure (Notebook on disk)
				subprocess.run(["npx", "-y", "specsmd@latest", "install"], check=True)

				# 2. Notify Success (Bünker mapping removed)
				from red_pill import __version__

				print(f"\n[OK] Flow '{args.flow}' initialized on disk (Notebook mode).")
				SovereignNotifier.notify_os(
					"Project Initialized", f"Red Pill v{__version__} + specs.md {args.flow} flow is now live.", category="init"
				)
			except Exception as e:
				print(f"[FAIL] Initialization failed: {e}")
			return
		elif args.command == "audit":
			handle_audit()
			return
		elif args.command == "heal":
			handle_heal(args.dry_run)
			return
		elif args.command == "doctor":
			from red_pill.metabolism.doctor import run_doctor

			sys.exit(run_doctor(getattr(args, "quiet", False)))
		elif args.command == "benchmark":
			handle_benchmark()
			return
		elif args.command == "identity":
			handle_identity(args)
		elif args.command == "interceptor":
			handle_interceptor(args)
			return
		elif args.command == "bunker":
			from red_pill.bunker_lifecycle import handle_bunker

			handle_bunker(args)
			return
		elif args.command == "ide":
			handle_ide(args)
			return
		elif args.command == "telegram":
			handle_telegram(args)
			return
		elif args.command == "license":
			handle_license(args)
			return
		elif args.command == "runtime":
			handle_runtime(args)
			return
		elif args.command == "media":
			from red_pill.media_cli import handle_media

			handle_media(args)
			return
		elif args.command == "job":
			handle_job(args)
			return
		elif args.command == "p2p":
			handle_p2p(args)
			return
		elif args.command == "memory":
			handle_memory(args)
			return
		elif args.command == "config":
			if args.config_cmd == "tui":
				from red_pill.config_tui import run_tui

				sys.exit(run_tui())
			else:
				config_parser.print_help()
				sys.exit(0)

		# Loop through requested collections
		for collection in collections:
			if args.command == "add":
				# D13: un alta manual (operador/agente) es un engrama "especial" →
				# `interactive_engram` (no se agrupa por sesión; lo trata el proceso
				# aparte de interactivos).
				metadata = {"node_type": "interactive_engram"} if collection in ("work_memories", "social_memories", "story_memories") else None
				manager.add_memory(collection, args.content, color=args.color, emotion=args.emotion, intensity=args.intensity, metadata=metadata)
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

				search_results = manager.search_and_reinforce(
					collection, args.query, limit=args.limit, deep_recall=is_deep, caller="cli_search", hybrid=True
				)
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
			elif args.command == "revision":
				from red_pill.metabolism.revision import backlog_count, drain, revise_classifications

				if args.backlog:
					counts = backlog_count(manager.client)
					print("--- [REVISION BACKLOG] ---")
					for col, count in counts.items():
						print(f"{col}: {count if count >= 0 else 'unavailable'} unreviewed engrams")
				elif args.drain:
					rev_results = drain(manager, batch_size=args.batch_size, dry_run=not args.execute)
					print(f"--- [REVISION DRAIN {'EXECUTE' if args.execute else 'DRY-RUN'}] ---")
					print(json.dumps(rev_results, indent=2))
				else:
					rev_results = revise_classifications(manager, dry_run=not args.execute)
					print(f"--- [REVISION BATCH {'EXECUTE' if args.execute else 'DRY-RUN'}] ---")
					print(json.dumps(rev_results, indent=2))
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
				if args.sig_cmd == "push":
					from red_pill.core.notifier import SovereignNotifier

					if not args.silent:
						SovereignNotifier.notify_os(args.title, args.message, sound=args.sound, category="manual")

					# Record memory of the signal (System Signal collections)
					manager.inject_signal(name=args.title, intensity=args.intensity, signal_type="manual", source="cli")
					print(f"[SAS] Signal recorded: {args.message}")

				elif args.sig_cmd == "evaporate":
					if args.all:
						manager.evaporate_signals(name=None)
						print("[SAS] Neural Reset: All signals cleared.")
					elif args.name:
						manager.evaporate_signals(name=args.name)
						print(f"[SAS] Signal '{args.name}' evaporated.")
					else:
						print("[FAIL] Specify --name or --all to evaporate.")

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
