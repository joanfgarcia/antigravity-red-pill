import argparse
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
	handle_ide,
	handle_identity,
	handle_interceptor,
	handle_license,
	handle_memory,
	handle_mode,
	handle_p2p,
	handle_pact,
	handle_runtime,
	handle_telegram,
	handle_telemetry,
	load_plugins,
	seal_pact,
	switch_skin,
)
from red_pill.cli_jobs import handle_job
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

	pact_parser = subparsers.add_parser("pact", help="Ritual del Pacto: nombrado (identidad + 760), sellado (770) o estado")
	pact_parser.add_argument("level", nargs="?", choices=["760", "770"], help="Omit para ver el estado; 770 sella el Pacto, 760 vuelve a Awakened")
	pact_parser.add_argument("--naming", action="store_true", help="Ceremonia de NOMBRADO: fija el nombre (identidad + pacto 760)")
	pact_parser.add_argument("--grant", action="store_true", help="770: llave del OPERADOR (otorga el covenant)")
	pact_parser.add_argument("--accept", action="store_true", help="770: llave del AGENTE (acepta el covenant)")
	pact_parser.add_argument("--yes", "--force", action="store_true", help="Bypass the covenant confirmation prompt")
	pact_parser.add_argument("--identity", default=None, help="Fichero con el engrama de identidad redactado por el agente (lo exige el NOMBRADO)")

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

	revision_parser = subparsers.add_parser("revision", help="Retroactive category revision (Track R2)")
	revision_parser.add_argument("--drain", action="store_true", help="Serial batches until the backlog is empty")
	revision_parser.add_argument("--execute", action="store_true", help="Actually move engrams (default: dry-run marks only)")
	revision_parser.add_argument("--batch-size", type=int, default=200, help="Engrams per batch (drain mode)")
	revision_parser.add_argument("--backlog", action="store_true", help="Only report the unreviewed backlog and exit")

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

	doctor_parser = subparsers.add_parser("doctor", help="Verificación síncrona config<->runtime (post-install/update)")
	doctor_parser.add_argument("--quiet", action="store_true", help="Solo el veredicto (oculta info no-bloqueante)")

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
	backend_parser.add_argument("value", nargs="?", choices=["agy", "grpc", "claude", "local", "auto"], help="Backend to use")
	ide_sub.add_parser("status", help="Show IDE bridge capabilities and health")
	ide_sub.add_parser("test", help="Run connectivity test against the IDE")

	# Telegram bridge utilities (RFC_TELEGRAM_RESILIENCE) — scripts tontos, sin agente
	tg_parser = subparsers.add_parser("telegram", help="Telegram bridge utilities (catalogo/cola)")
	tg_sub = tg_parser.add_subparsers(dest="telegram_cmd")
	tg_models = tg_sub.add_parser("models", help="List curated model catalog (no shell a 'opencode models')")
	tg_models.add_argument("--backend", choices=["opencode", "claude", "agy", "local"], help="Filter models by backend")
	tg_sub.add_parser("roles", help="List role aliases and their cascade")
	tg_queue = tg_sub.add_parser("queue", help="Show queue + inbox/outbox state")
	tg_queue.add_argument("--limit", type=int, default=50, help="Max jobs to show (default 50)")

	license_parser = subparsers.add_parser("license", help="Compliance audit: licencias de modelos y contexto")
	license_parser.add_argument("--json", action="store_true", help="Salida estructurada JSON para parseo agéntico")

	# AD-049: registro de runtimes de inferencia (múltiples llama.cpp)
	runtime_parser = subparsers.add_parser("runtime", help="Registro de runtimes de inferencia (AD-049)")
	runtime_sub = runtime_parser.add_subparsers(dest="runtime_cmd")
	runtime_sub.add_parser("list", help="Lista los runtimes declarados y su disponibilidad")
	runtime_check = runtime_sub.add_parser("check", help="Resuelve el runtime de un perfil y comprueba disponibilidad")
	runtime_check.add_argument("profile", help="Nombre del perfil (model_profiles.yaml)")
	runtime_stop = runtime_sub.add_parser("stop", help="Abate servidores dedicados (swap-o-defer, AD-049)")
	runtime_stop.add_argument("profile", nargs="?", help="Perfil cuyo servidor dedicado abatir")
	runtime_stop.add_argument("--all", action="store_true", help="Abatir todos los servidores dedicados vivos")

	# docs/CORE/MEDIA_MODELS.md: media generativa — router por tarea, staging y promoción
	media_parser = subparsers.add_parser("media", help="Media generativa: router por tarea, staging y promoción (docs/CORE/MEDIA_MODELS.md)")
	media_sub = media_parser.add_subparsers(dest="media_cmd")
	media_resolve = media_sub.add_parser("resolve", help="Resuelve task -> modelo del elenco media")
	media_resolve.add_argument("--task")
	media_resolve.add_argument("--model")
	media_validate = media_sub.add_parser("validate", help="Valida/rutea una petición de generación (JSON)")
	media_validate.add_argument("--task")
	media_validate.add_argument("--model")
	media_validate.add_argument("--width", type=int)
	media_validate.add_argument("--height", type=int)
	media_adapt = media_sub.add_parser("adapt", help="Adapta dimensiones para un modelo (JSON)")
	media_adapt.add_argument("--model", required=True)
	media_adapt.add_argument("--width", type=int)
	media_adapt.add_argument("--height", type=int)
	media_staging = media_sub.add_parser("staging", help="Muestra/crea el dir de staging de un encargo")
	media_staging.add_argument("--title")
	media_promote = media_sub.add_parser("promote", help="Promociona un artefacto del staging a destino definitivo")
	media_promote.add_argument("title", help="Title del encargo en el staging")
	media_promote.add_argument("--to", required=True, help="Destino definitivo (dir)")
	media_promote.add_argument("--name", help="Fichero concreto a promocionar")
	media_promote.add_argument("--move", action="store_true", help="Mover en vez de copiar")

	# Centralized Job Manager
	job_parser = subparsers.add_parser("job", help="Centralized Job Manager (deferred, resumable jobs)")
	job_sub = job_parser.add_subparsers(dest="job_cmd")

	job_submit = job_sub.add_parser("submit", help="Encolar un job diferido (BACKGROUND_DEFERRED)")
	job_submit.add_argument(
		"--recipe", help="Receta YAML del satélite (ruta, o nombre corto buscado en .red-pill/jobs/). Sustituye a --source/--payload"
	)
	job_submit.add_argument("--source", help="Source del driver que lo ejecuta (p.ej. script_job). Innecesario con --recipe")
	job_submit.add_argument("--payload", default="{}", help="Payload JSON del job")
	job_submit.add_argument("--priority", type=int, default=5, help="Prioridad (mayor = más urgente, default 5)")
	job_submit.add_argument(
		"--singleton", action="store_true", help="No encolar si ya hay un job vivo (PENDING/PROCESSING/PAUSED/BLOCKED) con el mismo source y title"
	)
	job_submit.add_argument("--title", help="Título descriptivo (se guarda en el payload)")
	job_submit.add_argument(
		"--kick",
		action="store_true",
		help="Disparar el runner de cola al momento (sin esperar al timer de 1 min). Útil al encolar una tarea y querer que la procese ya.",
	)
	job_submit.add_argument("--parent", help="Id del job padre: entra BLOCKED y se desbloquea cuando el padre completa (DAG)")
	job_submit.add_argument("--mission", help="Grupo de aislamiento entre forges (mission_id)")
	job_submit.add_argument("--paused", action="store_true", help="Encolar el job ya PAUSADO: nace sin que el runner lo toque hasta `job resume`.")
	job_submit.add_argument(
		"--allow-tmp", action="store_true", help="Permitir rutas volátiles (/tmp, /dev/shm, /run/user) en el payload: no sobreviven a un reinicio."
	)

	job_list = job_sub.add_parser("list", help="Listar jobs activos, pausados y en cola")
	job_list.add_argument("--all", action="store_true", help="Incluir también COMPLETED")
	job_list.add_argument("--mission", help="Solo jobs de esa misión (aislamiento entre forges)")
	job_list.add_argument(
		"--json",
		action="store_true",
		help="JOB-001: salida estructurada JSON (id/source/status/prio/mission/parent/progress/attempts/updated_at/title) para parseo agéntico",
	)

	job_status = job_sub.add_parser("status", help="Detalle completo de un job (checkpoint, progreso)")
	job_status.add_argument("job_id", help="Id completo o prefijo corto")

	job_pause = job_sub.add_parser("pause", help="Pausar un job (el runner no ejecuta el siguiente step)")
	job_pause.add_argument("job_id", help="Id completo o prefijo corto")

	job_resume = job_sub.add_parser("resume", help="Reanudar un job pausado desde su checkpoint")
	job_resume.add_argument("job_id", help="Id completo o prefijo corto")

	job_skip = job_sub.add_parser("skip", help="Saltar el siguiente elemento/step sin reintentarlo (marca skip_next en el checkpoint)")
	job_skip.add_argument("job_id", help="Id completo o prefijo corto")

	job_kill = job_sub.add_parser("kill", help="Abatir el step en vuelo (duro): PAUSED* reanudable, con marca de kill sucio")
	job_kill.add_argument("job_id", help="Id completo o prefijo corto")
	job_kill.add_argument("--discard", action="store_true", help="Cancelar definitivamente: FRUSTRATED en lugar de reanudable")
	job_cancel = job_sub.add_parser("cancel", help="Cancelar un job en espera (PENDING/BLOCKED u otros): FRUSTRATED limpio + cascada a hijos BLOCKED")
	job_cancel.add_argument("job_id", help="Id completo o prefijo corto")

	job_logs = job_sub.add_parser("logs", help="Salida del proceso hijo de un job (stdout/stderr por step)")
	job_logs.add_argument("job_id", help="Id completo o prefijo corto")
	job_logs.add_argument("--tail", type=int, default=50, help="Últimas N líneas (default 50)")

	job_purge = job_sub.add_parser("purge", help="Retirar jobs terminales de la cola (FRUSTRATED/COMPLETED; PAUSED solo con --force)")
	job_purge.add_argument("job_ids", nargs="*", help="Ids completos o prefijos cortos")
	job_purge.add_argument("--terminal", action="store_true", help="Barrer todos los FRUSTRATED y COMPLETED de una vez")
	job_purge.add_argument("--force", action="store_true", help="Permitir purgar un job PAUSED (solo por id, nunca en barrido)")
	job_purge.add_argument("--yes", action="store_true", help="Sin confirmación interactiva")

	job_sub.add_parser("process-queue", help="Runner shot-and-forget: procesa la cola y se apaga (exit 0)")
	job_sub.add_parser("kick", help="Disparar el runner de cola inmediatamente (sin esperar al timer de 1 min)")

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

	# Workspace Memory Management (B.1)
	memory_parser = subparsers.add_parser("memory", help="Manage workspace-local memory filing cabinet")
	memory_sub = memory_parser.add_subparsers(dest="mem_cmd")

	memory_sub.add_parser("sync", help="Synchronize engrams into all enabled workspace memory directories")
	memory_sub.add_parser("optimize", help="Run LLM-compaction/optimization across all enabled workspace memories")

	memory_enable = memory_sub.add_parser("enable", help="Enable memory serving for a workspace")
	memory_enable.add_argument("workspace", help="Workspace name or root directory path")
	memory_enable.add_argument("--path", help="Optional custom memory directory path (relative or absolute)")

	memory_disable = memory_sub.add_parser("disable", help="Disable memory serving for a workspace")
	memory_disable.add_argument("workspace", help="Workspace name or root directory path")

	# Central configuration TUI (B.2)
	config_parser = subparsers.add_parser("config", help="Manage central configuration settings")
	config_sub = config_parser.add_subparsers(dest="config_cmd")
	config_sub.add_parser("tui", help="Interactive TUI configuration manager and dashboard")

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

	elif args.command == "pact":
		handle_pact(args)
		return

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
