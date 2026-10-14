"""CLI command handlers — one cohesive module per concern, split from cli.py (SHARD-PS-04).

Holds the individual command handlers (pact/mode/identity/interceptor/ide/runtime/
license/telegram/p2p/memory/daemon/secrets + audit/heal/benchmark/telemetry), the
plugin registry and the skin/pact helpers. `main()` (in cli.py) dispatches here.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
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
		from red_pill.swarm.bridges import create_bridge, preflight_check

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
		from red_pill.swarm.bridges import create_bridge

		bridge = create_bridge()
		backend_name = bridge.get_capabilities().backend.value.upper()
		print(f"Testing {backend_name} bridge...")
		if bridge.health_check():
			print(f"[OK] {backend_name} bridge is healthy.")
		else:
			print(f"[FAIL] {backend_name} bridge is not responding.")
	else:
		print("Usage: red-pill ide [backend|status|test]")


def handle_runtime(args: argparse.Namespace) -> None:
	"""Registro de runtimes de inferencia (AD-049): list / check."""
	from red_pill.core.model_registry import ModelRegistry
	from red_pill.core.paths import get_runtimes_path
	from red_pill.core.runtime_registry import RuntimeRegistry

	cmd = getattr(args, "runtime_cmd", None)

	if cmd == "check":
		profile_name = args.profile
		profile = ModelRegistry.get_profile(profile_name)
		if not profile:
			print(f"⛔ Perfil '{profile_name}' no existe en model_profiles.yaml")
			return
		declared = bool(profile.get("runtime"))
		runtime_id = profile.get("runtime") or RuntimeRegistry.default_id()
		rt = RuntimeRegistry.get(runtime_id)
		variant = rt.get("variant")
		ok, reason = RuntimeRegistry.check_available(runtime_id)
		tag = ("declarado" if declared else "default") + (f", variante {variant}" if variant else "")
		if ok:
			print(f"✅ '{profile_name}' → runtime '{runtime_id}' ({tag}) disponible")
		else:
			print(f"⛔ '{profile_name}' → runtime '{runtime_id}' ({tag}): {reason}")
		return

	if cmd == "stop":
		from red_pill.inference.runtime_server import running_servers, stop_dedicated_servers

		if getattr(args, "all", False):
			print(f"🛑 Servidores dedicados detenidos: {stop_dedicated_servers()}")
		elif getattr(args, "profile", None):
			stopped = stop_dedicated_servers(profile_name=args.profile)
			if stopped:
				print(f"🛑 '{args.profile}': {stopped} servidor(es) detenido(s)")
			else:
				print(f"(sin servidor vivo para '{args.profile}')")
		else:
			alive = running_servers()
			names = ", ".join(str(s.get("profile")) for s in alive) or "(ninguno)"
			print(f"Usa `<perfil>` o `--all`. Servidores vivos: {names}")
		return

	# list (default)
	runtimes = RuntimeRegistry.all()
	if not runtimes:
		print(f"🧩 Sin runtimes declarados en {get_runtimes_path()}")
		return
	print(f"🧩 Runtimes de inferencia ({len(runtimes)}) — default: {RuntimeRegistry.default_id()}")
	for rid, rt in runtimes.items():
		ok, reason = RuntimeRegistry.check_available(rid)
		mark = "✅" if ok else "⛔"
		tail = "" if ok else f"  — {reason}"
		variants = RuntimeRegistry.variants(rid)
		bin_field = rt.get("binary") or (f"({len(variants)} variantes)" if variants else "?")
		print(f"  {mark} {rid:<20} {str(rt.get('kind', '?')):<16} {bin_field}{tail}")
		for vid, v in variants.items():
			vok = "✅" if v.get("available") else "⛔"
			dmark = " (default)" if vid == rt.get("default_variant") else ""
			print(f"      {vok} variante {vid}{dmark} — {v.get('binary') or '(sin binario)'}")

	from red_pill.inference.runtime_server import running_servers

	alive = running_servers()
	if alive:
		print(f"🟢 Servidores dedicados vivos ({len(alive)}):")
		for s in alive:
			print(f"  {str(s.get('profile')):<20} pid={s.get('pid')} :{s.get('port')} ctx={s.get('ctx')} kv={s.get('kv_type')}")


def handle_license(args: argparse.Namespace) -> None:
	"""Compliance audit: license of every curated/cataloged model + context state."""

	from red_pill.core.model_catalog import ModelCatalog, ModelCatalogError
	from red_pill.core.model_license import _env_commercial_context
	from red_pill.core.model_registry import ModelRegistry

	context = "commercial" if _env_commercial_context() else "personal"
	profiles = ModelRegistry.get_all_profiles()
	profile_rows = [
		{
			"name": name,
			"license_id": ModelRegistry.get_license(name).get("id", "undeclared"),
			"commercial_ok": ModelRegistry.get_license(name).get("commercial_ok", False),
			"known": ModelRegistry.get_license(name).get("known", False),
			"prompts_used_for_training": ModelRegistry.get_license(name).get("prompts_used_for_training", False),
			"confidential_ok": ModelRegistry.get_license(name).get("confidential_ok", False),
		}
		for name in sorted(profiles)
	]

	try:
		catalog = ModelCatalog()
		models = catalog.models()
	except ModelCatalogError:
		models = []
	catalog_rows = [
		{
			"id": m["id"],
			"license_id": catalog.license_for(m["id"]).get("id", "undeclared"),
			"commercial_ok": catalog.license_for(m["id"]).get("commercial_ok", False),
			"known": catalog.license_for(m["id"]).get("known", False),
			"prompts_used_for_training": catalog.license_for(m["id"]).get("prompts_used_for_training", False),
			"confidential_ok": catalog.license_for(m["id"]).get("confidential_ok", False),
		}
		for m in models
	]

	if getattr(args, "json", False):
		print(json.dumps({"context": context, "profiles": profile_rows, "catalog": catalog_rows}, indent=2, ensure_ascii=False))
		return

	print(f"⚖️  Contexto de licencia: {context.upper()}  (REDPILL_LICENSE_CONTEXT={'commercial' if context == 'commercial' else 'personal'})")
	print()

	if profile_rows:
		print(f"📦 Perfiles locales ({len(profile_rows)}):")
		for row in profile_rows:
			flag = "✅ comercial" if row["commercial_ok"] else "⛔ NO comercial"
			known = "" if row["known"] else " (licencia no reconocida → fail-closed)"
			print(f"  {row['name']:<22} {flag:<14} {row['license_id']}{known}")
		print()

	if catalog_rows:
		print(f"🧠 Catálogo curado ({len(catalog_rows)}):")
		for row in catalog_rows:
			flag = "✅" if row["commercial_ok"] else "⛔"
			priv = ""
			# Los marcadores de privacidad solo se muestran cuando hay riesgo REAL
			# declarado (opt-in de entrenamiento). Un API/local sin esa excepción
			# no merece un icono alarmista.
			if row["prompts_used_for_training"]:
				priv += " ⚠️ENTRENAMIENTO"
				if not row["confidential_ok"]:
					priv += " 🔒NO-CONFIDENCIAL"
			print(f"  {row['id']:<40} {flag} {row['license_id']}{priv}")
		print()

	if context == "commercial":
		nc_models = [row["name"] for row in profile_rows if not row["commercial_ok"]]
		if nc_models:
			print(f"⚠️  EN CONTEXTO COMERCIAL, estos modelos están BLOQUEADOS: {', '.join(nc_models)}")
			print("    El gate impedirá que el daemon/distiller los use.")
		else:
			print("✅ Ningún perfil local bloqueado en contexto comercial.")


def handle_telegram(args: argparse.Namespace) -> None:
	"""Telegram bridge utilities — scripts tontos de solo lectura (RFC §2A/D6/D20)."""
	if args.telegram_cmd == "models":
		from red_pill.core.model_catalog import ModelCatalog, ModelCatalogError

		try:
			catalog = ModelCatalog()
			models = catalog.models(backend=args.backend)
		except ModelCatalogError as e:
			print(f"[ERROR] {e}")
			return
		if not models:
			print(f"[INFO] No hay modelos curados para backend={args.backend or 'todos'}.")
			return
		print(f"🧠 Modelos curados ({len(models)}):")
		for i, m in enumerate(models, start=1):
			roles = ", ".join(m.get("roles", [])) or "-"
			print(f"  {i}. {m['id']}  [tier={m.get('tier')}] [priority={m.get('priority')}] [roles={roles}]")
	elif args.telegram_cmd == "roles":
		from red_pill.core.model_catalog import ModelCatalog, ModelCatalogError

		try:
			catalog = ModelCatalog()
		except ModelCatalogError as e:
			print(f"[ERROR] {e}")
			return
		print("🎭 Roles definidos:")
		for role in catalog.role_names():
			cascade = [m["id"] for m in catalog.cascade_for(role=role)]
			print(f"  {role}: {', '.join(cascade)}")
	elif args.telegram_cmd == "queue":
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue = CognitiveQueueManager()
		tasks = queue.list_tasks(limit=args.limit)
		print(f"🗂️  Cola central ({len(tasks)} jobs activos):")
		for t in tasks[: args.limit]:
			title = (t.get("title") or "")[:60]
			print(f"  {t['id'][:8]} {t['status']:<10} prio={t['priority']} {title}")
	else:
		print("Usage: red-pill telegram [models|roles|queue]")


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


def handle_memory(args) -> None:
	"""Workspace memory CLI handler."""
	from red_pill.memory import MemoryManager
	from red_pill.metabolism.memory_sync import (
		compact_all_workspaces,
		disable_workspace_memory,
		enable_workspace_memory,
		sync_all_workspaces,
	)

	if args.mem_cmd == "sync":
		print("\n🔄 --- [WORKSPACE MEMORY: SYNCHRONIZING] ---")
		sync_all_workspaces(MemoryManager())
		print("[OK] All workspace memories synchronized.")
	elif args.mem_cmd == "optimize":
		print("\n⚡ --- [WORKSPACE MEMORY: OPTIMIZING (COMPACTION)] ---")
		compact_all_workspaces(MemoryManager())
		print("[OK] Compaction cycle complete.")
	elif args.mem_cmd == "enable":
		print(f"\n📂 --- [WORKSPACE MEMORY: ENABLING {args.workspace}] ---")
		success = enable_workspace_memory(args.workspace, custom_path=args.path)
		if success:
			print(f"[OK] Memory serving enabled for {args.workspace}.")
		else:
			print(f"[FAIL] Could not enable memory for {args.workspace}.")
	elif args.mem_cmd == "disable":
		print(f"\n📂 --- [WORKSPACE MEMORY: DISABLING {args.workspace}] ---")
		success = disable_workspace_memory(args.workspace)
		if success:
			print(f"[OK] Memory serving disabled for {args.workspace}.")
		else:
			print(f"[FAIL] Could not disable memory for {args.workspace}.")
	else:
		print("Usage: red-pill memory [sync|optimize|enable|disable]")


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
