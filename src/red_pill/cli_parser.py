"""CLI argument parser — the full subcommand tree, split from cli.py (SHARD-PS-04).

`main()` (cli.py) calls `build_parser()`. The `config` subparser is returned too,
because the dispatch chain needs it for the help fallback.
"""

from __future__ import annotations

import argparse

import red_pill.config as cfg
from red_pill.cli_commands import load_plugins


def build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
	"""Build the top-level parser and the `config` subparser it owns."""
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

	session_parser = subparsers.add_parser("session", help="Alma y Coro: espejo canónico de turnos y reencarnación")
	session_sub = session_parser.add_subparsers(dest="session_cmd")
	mirror_parser = session_sub.add_parser("mirror", help="Espejo canónico (session_mirror)")
	mirror_sub = mirror_parser.add_subparsers(dest="mirror_cmd")
	mirror_sync = mirror_sub.add_parser("sync", help="Vuelca transcripts de arnés al espejo (idempotente)")
	mirror_sync.add_argument("--continuity", help="Limita el backfill a un alma (continuity_id)")
	mirror_sync.add_argument("--originator", help="Limita el backfill a un leg (provider:session_id)")
	mirror_sub.add_parser("stats", help="Métricas del espejo (filas, almas, bytes, candidatos a purga)")
	session_rehydrate = session_sub.add_parser("rehydrate", help="Emite el bloque para reencarnar en un arnés externo")
	session_rehydrate.add_argument("--continuity", required=True, help="Alma a rehidratar (continuity_id)")
	session_rehydrate.add_argument("--limit", type=int, default=None, help="Máximo de turnos (los últimos)")
	session_rehydrate.add_argument("--kind", default="opencode", help="Arnés destino (solo etiqueta el bloque)")
	session_pending = session_sub.add_parser("pending", help="Turnos write-ahead pendientes/abortados (B-01s)")
	session_pending.add_argument("--continuity", default=None, help="Filtra por alma (continuity_id)")
	session_pending.add_argument("--json", action="store_true", help="Salida JSON")
	session_pending.add_argument("--expire", action="store_true", help="Marca aborted los pending que superan el TTL")
	session_pending.add_argument("--max-age-min", type=int, default=None, help="TTL manual para --expire (minutos)")
	session_resume = session_sub.add_parser("resume", help="Muestra el prompt de un turno pendiente/abortado")
	session_resume.add_argument("request_id", help="request_id del turno")
	session_resume.add_argument("--continuity", default=None, help="Filtra por alma (continuity_id)")
	session_resume.add_argument("--json", action="store_true", help="Salida JSON")
	session_compact = session_sub.add_parser("compact", help="Compacta el contexto de un alma (B-02)")
	session_compact.add_argument("--continuity", required=True, help="Alma a compactar (continuity_id)")
	session_compact.add_argument("--mission", default=None, help="Misión para el registro (default: la del último turno)")
	session_compact.add_argument("--engine", default=None, help="Motor: samantha | memento | extractive (default: config)")
	session_compact.add_argument("--protect-last-n", type=int, default=None, help="Turnos recientes que nunca se compactan")
	session_compact.add_argument("--handoff", default=None, help="Fichero con una nota de handoff: reset del contexto")
	session_compact.add_argument("--db-path", default=None, help="session.db alternativa (jobs de test/worktree)")
	session_compact.add_argument("--json", action="store_true", help="Salida JSON")
	session_decisions = session_sub.add_parser("decisions", help="Bandeja de D-obj pendientes (D23-SCORE)")
	session_decisions.add_argument("--mission", default=None, help="Filtra por misión")
	session_decisions.add_argument(
		"--state",
		action="append",
		choices=["open", "escalated", "upheld", "dismissed"],
		help="Estado a listar (repetible; default open/escalated)",
	)
	session_decisions.add_argument("--include-resolved", action="store_true", help="Incluye upheld/dismissed")
	session_decisions.add_argument("--limit", type=int, default=100, help="Máximo (default 100)")
	session_decisions.add_argument("--json", action="store_true", help="Salida JSON")
	session_moderate = session_sub.add_parser("moderate", help="Operador: flag/hide/retract/restore una nota")
	session_moderate.add_argument("event_id", help="event_id de la nota")
	session_moderate.add_argument("--action", required=True, choices=["flag", "hide", "retract", "restore"])
	session_moderate.add_argument("--reason", default="", help="Motivo (queda auditado)")
	session_moderate.add_argument("--json", action="store_true", help="Salida JSON")

	mini_parser = subparsers.add_parser("mini", help="Mini arnés local Forge/Loom (REPL o --once)")
	mini_parser.add_argument("--profile", default="forge", help="Perfil del cuerpo (forge | loom | loom-tools)")
	mini_parser.add_argument("--continuity", default=None, help="Alma (continuity_id); si se omite se emite una")
	mini_parser.add_argument("--mission", default="mission:mini-cli", help="Misión del job")
	mini_parser.add_argument("--workspace", default=None, help="Workspace con jaula de tools (default: cwd)")
	mini_parser.add_argument("--gpu-socket", default=None, help="UDS de Forge (default: MINI_FORGE_SOCKET)")
	mini_parser.add_argument("--flm-url", default=None, help="URL de Loom/FLM (default: MINI_FLM_URL)")
	mini_parser.add_argument("--db-path", default=None, help="session.db (default: la viva)")
	mini_parser.add_argument("--operator", default="Joan", help="Operador para el system prompt")
	mini_parser.add_argument("--once", default=None, metavar="PROMPT", help="Ejecuta un solo prompt y sale")

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
	job_list.add_argument("--continuity", help="Solo jobs de esa alma (continuity_id)")
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
	job_resume.add_argument("--force", action="store_true", help="Operador: reclamar la misión aunque el lease sea de otra alma.")

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

	return parser, config_parser
