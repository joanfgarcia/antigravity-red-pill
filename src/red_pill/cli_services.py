"""CLI service/integration handlers — identity, IDE, runtime, license, telegram,
p2p and workspace memory. Split from cli_commands.py (SHARD-PS-04).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Optional

import red_pill.config as cfg
from red_pill.core.paths import get_config_dir

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def run_mini_cli(bridge: Any, *, once: Optional[str] = None, input_fn: Any = input, output: Any = print) -> bool:
	"""REPL/one-shot sobre un MiniLocalBridge (inyectable para tests)."""

	def ask(prompt: str) -> bool:
		result = bridge.prompt(prompt)
		if getattr(result, "ok", False):
			output(result.response)
			return True
		output(f"[mini] error: {getattr(result, 'error', 'unknown')}")
		return False

	if once:
		return ask(once)
	output(f"[mini] profile={getattr(bridge, 'profile', '?')} continuity={getattr(bridge, 'continuity_id', '?')} (exit/quit para salir)")
	ok = True
	while True:
		try:
			line = input_fn("mini> ")
		except (EOFError, KeyboardInterrupt, StopIteration):
			break
		text = str(line or "").strip()
		if text.lower() in ("exit", "quit"):
			break
		if text:
			ok = ask(text) and ok
	return ok


def handle_mini(args: argparse.Namespace) -> int:
	"""CLI `red-pill mini`: un paso o REPL sobre Forge/Loom."""
	from red_pill.mini.bridge import MiniLocalBridge

	bridge = MiniLocalBridge(
		profile=args.profile,
		continuity_id=args.continuity,
		mission_id=args.mission,
		workspace=args.workspace,
		db_path=args.db_path,
		gpu_socket=args.gpu_socket,
		flm_url=args.flm_url,
		operator=args.operator,
	)
	return 0 if run_mini_cli(bridge, once=args.once) else 1


def handle_session(args: argparse.Namespace) -> None:
	"""Alma y Coro: operaciones sobre el espejo canónico de turnos."""
	if getattr(args, "session_cmd", None) == "mirror" and getattr(args, "mirror_cmd", None) == "sync":
		from red_pill.session.mirror import SessionMirror, sync_registry

		report = sync_registry(
			SessionMirror(),
			continuity_id=getattr(args, "continuity", None),
			originator=getattr(args, "originator", None),
		)
		inserted = sum(int(row.get("inserted") or 0) for row in report)
		for row in report:
			status = f"+{row['inserted']}" if not row.get("error") else f"ERROR: {row['error']}"
			print(f"[MIRROR] {row['originator']} ({row.get('provider') or '?'}): {status}")
		print(f"[MIRROR] legs={len(report)} turnos_insertados={inserted}")
		return
	if getattr(args, "session_cmd", None) == "mirror" and getattr(args, "mirror_cmd", None) == "stats":
		import json

		from red_pill.session.mirror import SessionMirror

		print(json.dumps(SessionMirror().stats(), ensure_ascii=False, indent=2))
		return
	if getattr(args, "session_cmd", None) == "pending":
		import json
		import time

		import red_pill.config as cfg
		from red_pill.session.external_turns import import_external_turns
		from red_pill.session.mirror import SessionMirror

		try:
			import_external_turns()
		except Exception:
			pass
		mirror = SessionMirror()
		if getattr(args, "expire", False):
			minutes = getattr(args, "max_age_min", None)
			if minutes is None:
				minutes = int(getattr(cfg.get_config(), "SESSION_PENDING_TTL_MIN", 30))
			expired = mirror.expire_pending_turns(max_age_s=max(0, int(minutes)) * 60, continuity_id=args.continuity)
			if not getattr(args, "json", False):
				print(f"[PENDING] expirados={expired} (ttl={minutes}m)")
		rows = mirror.pending_turns(args.continuity)
		if getattr(args, "json", False):
			print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
		elif not rows:
			print("[PENDING] sin turnos pendientes/abortados")
		else:
			now = time.time()
			for row in rows:
				age = max(0, int(now - float(row.get("ts") or now)))
				preview = " ".join(str(row.get("content") or "").split())[:160]
				print(f"[{str(row.get('status') or '?').upper()}] {row.get('request_id')} alma={row.get('continuity_id')} edad={age}s :: {preview}")
		return
	if getattr(args, "session_cmd", None) == "resume":
		import json

		from red_pill.session.mirror import SessionMirror

		request_id = str(getattr(args, "request_id", "") or "")
		rows = [r for r in SessionMirror().pending_turns(getattr(args, "continuity", None)) if str(r.get("request_id") or "") == request_id]
		if not rows:
			print(f"[RESUME] no hay turno pendiente/abortado con request_id={request_id!r}")
			return
		if getattr(args, "json", False):
			print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
			return
		for row in rows:
			print(f"[RESUME] request_id={row.get('request_id')} status={row.get('status')} alma={row.get('continuity_id')} mission={row.get('mission_id')}")
			print(str(row.get("content") or ""))
			print("[RESUME] --- fin del prompt ---")
		return
	if getattr(args, "session_cmd", None) == "compact":
		import json

		from red_pill.session.compactor import Compactor
		from red_pill.session.mirror import SessionMirror

		mirror = SessionMirror(getattr(args, "db_path", None))
		compactor = Compactor(
			mirror,
			engine=getattr(args, "engine", None),
			protect_last_n=getattr(args, "protect_last_n", None),
		)
		handoff = getattr(args, "handoff", None)
		done: Optional[dict]
		if handoff:
			from pathlib import Path as _Path

			try:
				summary = _Path(handoff).read_text(encoding="utf-8")
			except OSError as exc:
				print(f"[COMPACT] no se pudo leer el handoff {handoff!r}: {exc}")
				raise SystemExit(1) from exc
			if not summary.strip():
				print(f"[COMPACT] el handoff {handoff!r} está vacío")
				raise SystemExit(1)
			mission = args.mission
			if not mission:
				latest = mirror.latest_compaction(args.continuity)
				mission = str((latest or {}).get("mission_id") or "")
			if not mission:
				turns = mirror.read_turns(args.continuity)
				mission = str((turns[0].get("mission_id") if turns else "") or "")
			if not mission:
				print("[COMPACT] --mission es obligatorio si el alma no tiene turnos previos")
				raise SystemExit(1)
			done = compactor.reset(args.continuity, summary=summary, mission_id=mission)
			action = "handoff"
		else:
			done = compactor.compact_now(args.continuity, mission_id=args.mission)
			action = "compact"
		if getattr(args, "json", False):
			print(json.dumps(done, ensure_ascii=False, indent=2, default=str))
		elif done is None:
			print(f"[COMPACT] {args.continuity}: nada que compactar (rango vacío)")
		else:
			print(
				f"[COMPACT] {action} {done.get('compaction_id')} "
				f"rango={done.get('range_start_seq')}-{done.get('range_end_seq')} "
				f"estado={done.get('status')}"
			)
		return
	if getattr(args, "session_cmd", None) == "rehydrate":
		from red_pill.session.switch import rehydrate_payload

		print(
			rehydrate_payload(
				args.continuity,
				limit=getattr(args, "limit", None),
				kind=getattr(args, "kind", "opencode") or "opencode",
			)
		)
		return
	if getattr(args, "session_cmd", None) == "decisions":
		import json

		from red_pill.session.store import SessionRegistry

		rows = SessionRegistry().list_decisions(
			mission_id=getattr(args, "mission", None),
			states=getattr(args, "state", None),
			limit=int(getattr(args, "limit", 100) or 100),
			pending_only=not getattr(args, "include_resolved", False),
		)
		if getattr(args, "json", False):
			print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
			return
		if not rows:
			print("[DECISIONS] sin decisiones pendientes.")
			return
		ops = sum(1 for row in rows if row.get("requires_operator"))
		print(f"--- DECISIONES ({len(rows)}; {ops} requieren Operador) ---")
		for row in rows:
			tag = "OP" if row.get("requires_operator") else "AG"
			age = max(0, int(row.get("age_s") or 0))
			print(
				f"[{tag}] {row.get('decision_id')} · sev={row.get('severity')} · "
				f"{row.get('proposed_action')} · state={row.get('state')} · "
				f"by={str(row.get('created_by'))[:8]} · age={age // 60}m · mission={row.get('mission_id')}"
			)
			if row.get("note_summary"):
				ref = f" · {row.get('note_ref')}" if row.get("note_ref") else ""
				note = " ".join(str(row.get("note_summary") or "").split())[:160]
				print(f"     nota: {note}{ref}")
		return
	if getattr(args, "session_cmd", None) == "moderate":
		import json

		from red_pill.session.store import SessionRegistry

		result = SessionRegistry().moderate_note(
			args.event_id,
			action=args.action,
			actor="operator",
			reason=getattr(args, "reason", ""),
		)
		if getattr(args, "json", False):
			print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
			return
		print(
			f"[MODERATE] {result['event_id']} → {result['status']} ({result['action']}); "
			f"D-obj resueltas={result['resolved_decisions']}"
		)
		return
	print("[MIRROR] uso: red-pill session mirror sync [--continuity ID | --originator LEG]")


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
