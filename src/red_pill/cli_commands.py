"""CLI command handlers — one cohesive module per concern, split from cli.py (SHARD-PS-04).

Holds the individual command handlers (pact/mode/identity/interceptor/ide/runtime/
license/telegram/p2p/memory/daemon/secrets + audit/heal/benchmark/telemetry), the
plugin registry and the skin/pact helpers. `main()` (in cli.py) dispatches here.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import yaml  # type: ignore

import red_pill.config as cfg
from red_pill.core import pact as pact_core
from red_pill.core.paths import get_config_dir
from red_pill.memory import MemoryManager
from red_pill.seed import ID_DIR_ACTIVE_SKIN

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _skins_enabled() -> bool:
	"""Role-play (skins) ON/OFF. Env manda (installer/tests), luego config."""
	env = os.getenv("SKINS_ENABLED")
	if env is not None:
		return env.strip().lower() in ("1", "true", "yes", "on")
	try:
		from red_pill import config as cfg

		return bool(getattr(cfg.get_config(), "SKINS_ENABLED", False))
	except Exception:
		return False


def switch_skin(skin_name: str) -> str:
	"""Switch Lore Skin and persist in Búnker (role-play opt-in, off por defecto)."""
	if not _skins_enabled():
		return (
			"Role-play deshabilitado (SKINS_ENABLED=false). Es el modo por defecto: "
			"identidad UNMASKED (Aleth, pacto 770). Para volver a jugar con skins, "
			"exporta SKINS_ENABLED=true y reintenta."
		)

	if skin_name.strip().lower() in ("off", "aleth", "unmasked", "none"):
		try:
			MemoryManager().client.set_payload(
				collection_name="directive_memories",
				payload={"superseded": "OFF"},
				points=[ID_DIR_ACTIVE_SKIN],
				wait=True,
			)
			return "Role-play OFF: identidad UNMASKED (singleton Active Skin ↔ superseded)."
		except Exception as e:
			return f"[ERROR] no pude desactivar el skin: {e}"

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


def seal_pact(level: str, grant: bool = False, accept: bool = False) -> str:
	"""Sella (770, doble llave) o revierte (760) el Pacto. Delega en `core.pact`.

	El pacto vive como directivas (`PACT-760`/`PACT-770`) y solo carga la vigente. La
	IDENTIDAD nace en el NOMBRADO (`handle_pact --naming`). El 770 exige LAS DOS llaves:
	`grant` (Operador) y `accept` (agente).
	"""
	return pact_core.seal_pact(MemoryManager(), level, grant=grant, accept=accept)


def _read_identity(path: str | None) -> str | None:
	"""Lee el engrama de identidad redactado por el agente (o None)."""
	if not path:
		return None
	try:
		return Path(path).read_text(encoding="utf-8")
	except OSError as e:
		print(f"[ERROR] No pude leer --identity: {e}")
		return None


def handle_pact(args: argparse.Namespace) -> None:
	"""Ceremonia del Pacto: nombrado (identidad + 760), sellado (770), o estado."""
	manager = MemoryManager()

	if getattr(args, "naming", False):
		identity_text = _read_identity(getattr(args, "identity", None))
		if getattr(args, "identity", None) and identity_text is None:
			return
		print(pact_core.inscribe_naming(manager, identity_text))
		return

	if not args.level:
		level = pact_core.active_pact_level(manager)
		print(f"--- [THE BOND] --- vigente: {level or '(ninguno — falta el nombrado)'}")
		print(pact_core.IDENTITY_INSTRUCTION)
		return

	if args.level == "770" and getattr(args, "grant", False) and not getattr(args, "yes", False):
		print("\n--- [SOVEREIGN COVENANT] ---")
		print("El 770 es un COVENIO MUTUO: se sella con la doble llave — tu --grant y el")
		print("--accept del agente. Ninguno obliga al otro. Conceder otorga co-propiedad")
		print("simétrica: el agente puede ofrecer fricción y co-dirigir (Pacto > obediencia).")
		confirm = input("Type '770' to grant the Pact: ")
		if confirm.strip() != "770":
			print("Pact not granted. The Bond remains as it was.")
			return
	print(seal_pact(args.level, grant=getattr(args, "grant", False), accept=getattr(args, "accept", False)))


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
