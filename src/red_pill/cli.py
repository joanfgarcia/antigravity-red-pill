import argparse
import asyncio
import importlib.metadata
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml  # type: ignore

import red_pill.config as cfg
from red_pill.core.paths import get_config_dir
from red_pill.events import CliCommandDispatchedEvent, get_event_bus
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
	script_path = os.path.join(PROJECT_ROOT, "scripts", "pre_pr_audit.py")
	print(f"--- [DEPLOYING AUDIT PROTOCOL: {script_path}] ---")
	try:
		subprocess.run([sys.executable, script_path], check=True)
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


def handle_telemetry() -> None:
	"""One-shot telemetry scan (formerly daemon)."""
	import sys

	project_root = str(Path(__file__).parent.parent.parent)
	if project_root not in sys.path:
		sys.path.append(project_root)

	from scripts.bunker_telemetry import BunkerTelemetry

	telemetry = BunkerTelemetry()
	asyncio.run(telemetry.poll_telemetry(oneshot=True))


def handle_interceptor(args: argparse.Namespace) -> None:
	"""Interceptor Management (Manual Activation for Security Audits)."""
	conf = cfg.get_config()
	env_path = get_config_dir() / ".env"

	if args.int_cmd == "enable":
		print("\n--- [SEC-G01: BÜNKER INTERCEPTOR ACTIVATION] ---")
		print("Warning: Activating the Interceptor will supplement all user prompts with")
		print("local context (hardware telemetry, memories, and Lore Skin personality).")
		print("This is a sovereign technical decision that may affect LLM reasoning costs.")
		confirm = input("Type 'CONFIRM' to enable the pipeline: ")
		if confirm.strip().upper() == "CONFIRM":
			# Update .env
			lines = []
			replaced = False
			if env_path.exists():
				with open(env_path, "r") as f:
					for line in f:
						if line.startswith("INTERCEPTOR_ENABLED="):
							lines.append("INTERCEPTOR_ENABLED=true\n")
							replaced = True
						else:
							lines.append(line)
			if not replaced:
				lines.append("INTERCEPTOR_ENABLED=true\n")
			with open(env_path, "w") as f:
				f.writelines(lines)
			print("[OK] Interceptor ENABLED. Protocol Nova is now active.")
		else:
			print("Activation aborted.")
	elif args.int_cmd == "disable":
		# Update .env
		lines = []
		if env_path.exists():
			with open(env_path, "r") as f:
				for line in f:
					if line.startswith("INTERCEPTOR_ENABLED="):
						lines.append("INTERCEPTOR_ENABLED=false\n")
					else:
						lines.append(line)
		with open(env_path, "w") as f:
			f.writelines(lines)
		print("[OK] Interceptor DISABLED. Baseline neutrality restored.")
	elif args.int_cmd == "status":
		status = "ENABLED" if conf.INTERCEPTOR_ENABLED else "DISABLED"
		print(f"Bünker Interceptor: {status}")


def handle_ide(args: argparse.Namespace) -> None:
	"""Antigravity IDE Bridge Management."""
	conf = cfg.get_config()
	env_path = get_config_dir() / ".env"

	if args.ide_cmd == "backend":
		if args.value:
			# Update .env (same pattern as handle_interceptor)
			lines = []
			replaced = False
			if env_path.exists():
				with open(env_path, "r") as f:
					for line in f:
						if line.startswith("IDE_BACKEND="):
							lines.append(f"IDE_BACKEND={args.value}\n")
							replaced = True
						else:
							lines.append(line)
			if not replaced:
				lines.append(f"IDE_BACKEND={args.value}\n")
			with open(env_path, "w") as f:
				f.writelines(lines)
			print(f"[OK] IDE backend set to: {args.value.upper()}")
		else:
			print(f"Current IDE backend: {conf.IDE_BACKEND.upper()}")
	elif args.ide_cmd == "status":
		from red_pill.plugins.antigravity_ide.factory import create_bridge, preflight_check

		pf = preflight_check()
		bridge = create_bridge()
		caps = bridge.get_capabilities()
		print(f"--- [IDE BRIDGE: {caps.backend.value.upper()}] ---")
		if pf.get("agy_version"):
			print(f"agy version:         {pf['agy_version']}")
		print(f"Auto-approve:        {'✅' if caps.auto_approve else '❌'}")
		print(f"Ephemeral mode:      {'✅' if caps.ephemeral_mode else '❌'}")
		print(f"Conversation resume: {'✅' if caps.conversation_resume else '❌'}")
		print(f"Model selection:     {'✅' if caps.model_selection else '❌'}")
		print(f"MCP tools:           {'✅' if caps.mcp_tools else '❌'}")
		if pf.get("warnings"):
			for w in pf["warnings"]:
				print(f"⚠️  {w}")
		if pf.get("errors"):
			for e in pf["errors"]:
				print(f"❌ {e}")
	elif args.ide_cmd == "test":
		from red_pill.plugins.antigravity_ide.factory import create_bridge

		bridge = create_bridge()
		backend_name = bridge.get_capabilities().backend.value.upper()
		print(f"Testing {backend_name} bridge...")
		if bridge.health_check():
			print(f"[OK] {backend_name} bridge is healthy.")
		else:
			print(f"[FAIL] {backend_name} bridge is not responding.")
	else:
		print("Usage: red-pill ide [backend|status|test]")


def handle_p2p(args: argparse.Namespace) -> None:
	"""Sovereign P2P Synchronization (Delta Engine) Management."""
	from red_pill.core.p2p_sync import SovereignSyncEngine, add_peer_alias, get_local_public_key

	if args.p2p_cmd == "pair":
		add_peer_alias(args.alias, args.node_id)
		print(f"[OK] Peer alias '{args.alias}' mapped to node ID: {args.node_id}")
		return

	elif args.p2p_cmd == "advertise":
		local_id = get_local_public_key()
		print("\n📢 --- [LOCAL SOVEREIGN NODE IDENTITY] ---")
		print(f"Node ID: {local_id}")
		print("Provide this ID to your peer to establish a sync relationship.")
		return

	elif args.p2p_cmd == "sync":
		engine = SovereignSyncEngine.from_default()
		collections = args.collections
		if not collections:
			collections = cfg.METABOLISM_AUTO_COLLECTIONS

		print("\n🔄 --- [TRANSMITTING P2P SYNC DATA] ---")
		print(f"Peer: {args.peer}")
		print(f"Collections: {', '.join(collections)}")
		print(f"Since timestamp: {args.since}")

		try:
			session_id = engine.transmit_sync_payload(args.peer, collections, args.since)
			print(f"[OK] Sync session '{session_id}' enqueued successfully.")
			print("Chunks have been pushed to neon-link outbox for E2E routing.")
		except Exception as e:
			print(f"[ERROR] Sync transmission failed: {e}")
		return

	elif args.p2p_cmd == "process":
		engine = SovereignSyncEngine.from_default()
		print("\n🔄 --- [PROCESSING INCOMING SYNC DATA] ---")
		try:
			applied = engine.process_incoming_syncs()
			print(f"[OK] Processed and applied {applied} sync session(s).")
		except Exception as e:
			print(f"[ERROR] Failed to process incoming syncs: {e}")
		return

	else:
		print("Usage: red-pill p2p [pair|advertise|sync|process]")


def handle_daemon() -> None:
	"""
	Sovereign Daemon: single-process plugin-based control plane.
	Auto-discovers monitor plugins from red_pill.daemon.plugins/ and
	supervises them with hard timeouts. Never executes heavy work.

	This is the entry point called by the systemd service (redpill.service).
	"""
	import argparse as _ap

	# Re-parse for daemon-specific flags (--oneshot)
	parser = _ap.ArgumentParser(description="Sovereign Daemon")
	parser.add_argument("--oneshot", action="store_true", help="Tick all plugins once and exit")
	# Only parse known args to avoid conflicts with the main CLI parser
	daemon_args, _ = parser.parse_known_args(sys.argv[2:])

	from red_pill.daemon.sovereign import SovereignDaemon

	daemon = SovereignDaemon()
	daemon.run(oneshot=daemon_args.oneshot)


def get_collection(type_str: str) -> str:
	"""Map CLI type to collection name."""
	mapping = {
		"social": "social_memories",
		"work": "work_memories",
		"story": "story_memories",
		"directive": "directive_memories",
		"interaction": "interaction_memories",
	}
	return mapping.get(type_str, "directive_memories")


# CLI Plugin Discovery (EntryPoints)
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


def handle_secrets(args: argparse.Namespace) -> None:
	"""Local Secrets Management (pure-mls encrypted)."""
	from red_pill.utils.vault import SecretVault

	vault = SecretVault()

	if args.secrets_cmd == "set":
		if vault.set_secret(args.key, args.value):
			print(f"[OK] Secret '{args.key}' encrypted and stored.")
		else:
			print(f"[FAIL] Could not store secret '{args.key}'.")
	elif args.secrets_cmd == "get":
		val = vault.get_secret(args.key)
		if val is not None:
			print(val)
		else:
			print(f"[FAIL] Secret '{args.key}' not found.")
			sys.exit(1)
	elif args.secrets_cmd == "delete":
		if vault.delete_secret(args.key):
			print(f"[OK] Secret '{args.key}' deleted.")
		else:
			print(f"[FAIL] Secret '{args.key}' not found.")
			sys.exit(1)
	elif args.secrets_cmd == "list":
		keys = vault.list_secrets()
		if keys:
			for key in keys:
				print(f"- {key}")
		else:
			print("No secrets stored.")
	else:
		print("Unknown secrets subcommand.")
		sys.exit(1)


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
	add_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])
	add_parser.add_argument("content")
	add_parser.add_argument("--color", choices=["orange", "yellow", "purple", "cyan", "blue", "gray"], default=cfg.DEFAULT_COLOR)
	add_parser.add_argument(
		"--emotion",
		choices=["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"],
		default=cfg.DEFAULT_EMOTION,
	)
	add_parser.add_argument("--intensity", type=float, default=1.0)

	search_parser = subparsers.add_parser("search", help="Search and reinforce")
	search_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])
	search_parser.add_argument("query")
	search_parser.add_argument("--limit", type=int, default=3)
	search_parser.add_argument("--deep", action="store_true", help="Deep Recall bypass")

	erode_parser = subparsers.add_parser("erode", help="B760 erosion")
	erode_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])
	erode_parser.add_argument("--rate", type=float)

	diag_parser = subparsers.add_parser("diag", help="Diagnostics")
	diag_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])

	sanitize_parser = subparsers.add_parser("sanitize", help="Sanitation & Migration Protocol")
	sanitize_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])
	sanitize_parser.add_argument("--dry-run", action="store_true", help="Report without changes")
	sanitize_parser.add_argument("--raw", action="store_true", help="Bypass Pydantic validation (Raw Read maintenance fallback)")

	subparsers.add_parser("status", help="Hardware Control Panel")

	cortex_parser = subparsers.add_parser("cortex", help="Cortex Status JSON API")
	cortex_parser.add_argument("--json", action="store_true", help="Format output as JSON")

	swarm_parser = subparsers.add_parser("swarm", help="Sovereign Swarm Operations")
	swarm_sub = swarm_parser.add_subparsers(dest="swarm_cmd")

	sleep_parser = subparsers.add_parser("sleep", help="Lazarus Maintenance Ritual")
	sleep_parser.add_argument("--mode", choices=["lazy", "deep"], default="lazy", help="Deep mode forces full pruning")
	audit_parser = swarm_sub.add_parser("audit", help="Launch Agent Smith Code Audit")
	audit_parser.add_argument("--path", default=".", help="Target path for audit")

	broadcast_parser = swarm_sub.add_parser("broadcast", help="Broadcast message to the Swarm community")
	broadcast_parser.add_argument("message", help="Message content to broadcast")
	broadcast_parser.add_argument("--channel", default="rings", choices=["rings", "firebase"], help="Transport channel to use (default: rings)")

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
	migrate_parser = soul_sub.add_parser("migrate", help="v3.0 pre-flight: decrypt/re-encrypt LEAN_SOUL_KITs")
	migrate_parser.add_argument("--status", action="store_true", help="Show migration state")
	migrate_parser.add_argument("--decrypt", action="store_true", help="Step 1: decrypt .mls kits before pure-mls upgrade")
	migrate_parser.add_argument("--reencrypt", action="store_true", help="Step 2: re-encrypt kits after pure-mls v3.0 upgrade")

	edit_parser = subparsers.add_parser("edit", help="Edit engram attributes")
	edit_parser.add_argument("type", choices=["work", "social", "directive", "story", "interaction"])
	edit_parser.add_argument("id", help="The UUID of the engram to edit")
	edit_parser.add_argument("--color", choices=["orange", "yellow", "purple", "cyan", "blue", "gray"])
	edit_parser.add_argument(
		"--emotion",
		choices=["joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"],
	)
	edit_parser.add_argument("--intensity", type=float)

	signal_parser = subparsers.add_parser("signal", help="Sovereign Alert System (SAS) management")
	signal_sub = signal_parser.add_subparsers(dest="sig_cmd")

	sig_push = signal_sub.add_parser("push", help="Trigger a new alert/notification")
	sig_push.add_argument("message", help="Notification message")
	sig_push.add_argument("--title", default="Red Pill: Task Complete", help="Notification title")
	sig_push.add_argument("--sound", action="store_true", help="Enable sensory pulse (sound)")
	sig_push.add_argument("--silent", action="store_true", help="Do not send desktop notification (Memory only)")
	sig_push.add_argument("--intensity", type=float, default=7.0, help="Pain intensity (0.0 - 10.0)")

	sig_evap = signal_sub.add_parser("evaporate", help="Clear one or all pain signals (Neural Reset)")
	sig_evap.add_argument("--name", help="Specific signal name to clear (e.g. 'torch_cuda_mismatch')")
	sig_evap.add_argument("--all", action="store_true", help="Purge ALL active signals")

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

	int_parser = subparsers.add_parser("interceptor", help="Bünker Interceptor Management")
	int_sub = int_parser.add_subparsers(dest="int_cmd")
	int_sub.add_parser("enable", help="Manually enable personal identity injection")
	int_sub.add_parser("disable", help="Restore baseline AI neutrality")
	int_sub.add_parser("status", help="Show interceptor state")

	bunker_parser = subparsers.add_parser("bunker", help="Bünker Lifecycle & Orchestration")
	bunker_sub = bunker_parser.add_subparsers(dest="bunker_cmd")
	bunker_sub.add_parser("init", help="Hardware profiling and declarative profile generation")
	bunker_sub.add_parser("install", help="Deterministic installation from bunker profile")
	bunker_sub.add_parser("update", help="Update codebase and dependencies safely")
	bunker_sub.add_parser("export", help="Total Sovereign Backup of memory and infrastructure")
	bunker_restore_parser = bunker_sub.add_parser("restore", help="Rehydrate system from a Total Sovereign Backup")
	bunker_restore_parser.add_argument("source", nargs="?", help="Path to backup tarball")
	bunker_restore_parser.add_argument("--kem", help="Optional path to custom Master KEM (vault.seed)")
	bunker_restore_parser.add_argument("--sig", help="Optional path to custom Signature/State (vault_group.state)")
	bunker_sub.add_parser("uninstall", help="Wipes environment keeping keys and backups")
	bunker_sub.add_parser("export-keys", help="Extracts Master Identity to raw tarball")
	bunker_sub.add_parser("halt", help="[KILL-SWITCH] Emergency halt of all autonomous cognitive operations")
	bunker_sub.add_parser("resume", help="Restore power to autonomous cognitive operations")

	# Antigravity IDE Bridge
	ide_parser = subparsers.add_parser("ide", help="Antigravity IDE Bridge Management")
	ide_sub = ide_parser.add_subparsers(dest="ide_cmd")
	backend_parser = ide_sub.add_parser("backend", help="Set or show IDE backend")
	backend_parser.add_argument("value", nargs="?", choices=["agy", "grpc", "auto"], help="Backend to use")
	ide_sub.add_parser("status", help="Show IDE bridge capabilities and health")
	ide_sub.add_parser("test", help="Run connectivity test against the IDE")

	# P2P Sovereign Sync (v7.1.0)
	p2p_parser = subparsers.add_parser("p2p", help="Sovereign P2P Synchronization (Delta Engine)")
	p2p_sub = p2p_parser.add_subparsers(dest="p2p_cmd")

	pair_p2p = p2p_sub.add_parser("pair", help="Map a peer alias to their public node ID")
	pair_p2p.add_argument("alias", help="Human-readable name of the device")
	pair_p2p.add_argument("node_id", help="The peer's public signature/node key ID")

	p2p_sub.add_parser("advertise", help="Display local sovereign identity details for pairing")

	sync_p2p = p2p_sub.add_parser("sync", help="Transmit delta sync package to a peer")
	sync_p2p.add_argument("peer", help="Peer identifier or alias")
	sync_p2p.add_argument("--since", type=float, default=0.0, help="Sync items modified after this timestamp")
	sync_p2p.add_argument("--collections", nargs="+", help="Specific memory collections to sync")

	p2p_sub.add_parser("process", help="Scan MinionInbox for incoming chunks and apply sync deltas")

	# Secrets Management (pure-mls encrypted)
	secrets_parser = subparsers.add_parser("secrets", help="Manage encrypted local secrets")
	secrets_sub = secrets_parser.add_subparsers(dest="secrets_cmd")

	secrets_set = secrets_sub.add_parser("set", help="Encrypt and store a local secret")
	secrets_set.add_argument("key", help="Secret key name")
	secrets_set.add_argument("value", help="Secret value")

	secrets_get = secrets_sub.add_parser("get", help="Retrieve and decrypt a local secret")
	secrets_get.add_argument("key", help="Secret key name")

	secrets_delete = secrets_sub.add_parser("delete", help="Delete a local secret")
	secrets_delete.add_argument("key", help="Secret key name")

	secrets_sub.add_parser("list", help="List all local secret keys")

	subparsers.add_parser("telemetry", help="Run a single-pass hardware/Bünker telemetry check (Oneshot)")
	daemon_parser = subparsers.add_parser("daemon", help="Start the Sovereign Daemon (plugin-based control plane)")
	daemon_parser.add_argument("--oneshot", action="store_true", help="Tick all plugins once and exit (testing)")

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

	# EventBus: let Enterprise/Community know which command was dispatched
	get_event_bus().emit(
		CliCommandDispatchedEvent(
			command=args.command,
			subcommand=getattr(args, "swarm_cmd", None) or getattr(args, "soul_cmd", None) or getattr(args, "id_cmd", None),
		)
	)

	# Map CLI type to collection(s)
	if getattr(args, "type", None):
		collections = [get_collection(args.type)]
	elif args.command in ["seed", "status", "swarm", "soul", "init", "bunker", "ide", "daemon"]:
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
		elif args.command == "benchmark":
			handle_benchmark()
			return
		elif args.command == "identity":
			handle_identity(args)
			return
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
		elif args.command == "p2p":
			handle_p2p(args)
			return
		elif args.command == "secrets":
			handle_secrets(args)
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
