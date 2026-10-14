"""CLI job domain — the Centralized Job Manager commands and their helpers.

Extracted from `cli.py` (SHARD-PS-04): a cohesive unit (submit/list/status/pause/
resume/skip/kill/cancel/logs/purge/process-queue/kick) plus the progress-display,
kill and lookup helpers. `main()` dispatches here via `handle_job`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

_VOLATILE_RE = re.compile(r"(?<![\w/.~-])/(?:tmp|dev/shm|run/user/\d+)/[^\s\"']*")


def _volatile_paths(payload: Dict[str, Any]) -> List[str]:
	"""Rutas del payload que no sobreviven a un reinicio (/tmp, /dev/shm, /run/user/N)."""
	return sorted(set(_VOLATILE_RE.findall(json.dumps(payload, ensure_ascii=False))))


def handle_job(args: argparse.Namespace) -> None:
	"""Centralized Job Manager: cola persistente compartida (bunker_queue.db)."""
	import json as _json

	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	queue = CognitiveQueueManager()

	if args.job_cmd == "submit":
		# D2: todo lo que entra por CLI es BACKGROUND_DEFERRED por definición.
		source, priority, parent = args.source, args.priority, getattr(args, "parent", None)

		if getattr(args, "recipe", None):
			# La forma humana: el payload vive en YAML, versionado en el repo del
			# satélite. Nadie debería teclear veinte claves JSON en una terminal.
			from red_pill.jobs.recipes import load_recipe

			try:
				source, payload, recipe_priority, recipe_parent, recipe_is_seed = load_recipe(args.recipe)
			except (FileNotFoundError, ValueError) as e:
				print(f"[ERROR] {e}")
				return
			# Fail-safe: una receta SEED (plantilla por-instalación) no es una
			# config activa. Los roles agénticos requieren modelos reales — si
			# la receta es seed, la instalación no está configurada: bloquea.
			if recipe_is_seed:
				cfg_source = payload.get("source", source)
				if cfg_source in ("agentic_job", "dag_job"):
					print(
						f"[ERROR] La receta '{args.recipe}' es un SEED genérico, no una config activa. "
						f"Activa la configuración real de esta instalación copiándola a .red-pill/jobs/ "
						f"y ajustando el modelo por rol (ver docs/TECHNICAL/DECISION_LOG.md). "
						f"Bloqueado por seguridad: no se encola un job agéntico sin modelos configurados."
					)
					return
			priority = args.priority if args.priority != 5 else recipe_priority
			parent = parent or recipe_parent
		else:
			if not args.source:
				print("[ERROR] indica --source (o --recipe con una receta YAML).")
				return
			try:
				payload = _json.loads(args.payload)
			except _json.JSONDecodeError as e:
				print(f"[ERROR] --payload debe ser JSON válido: {e}")
				return

		if args.title:
			payload["title"] = args.title

		mission = getattr(args, "mission", None) or payload.get("mission_id")

		# Los timers de calendario re-encolan a diario: si el job de ayer sigue
		# vivo (p.ej. deferido toda la noche), duplicarlo solo ensucia la cola.
		if getattr(args, "singleton", False):
			active = queue.list_tasks(statuses=["PENDING", "PROCESSING", "PAUSED", "BLOCKED"])
			twin = next((t for t in active if t["source"] == source and t.get("title") == payload.get("title")), None)
			if twin:
				print(f"[OK] Ya hay un job vivo equivalente ({twin['id'][:8]}, {twin['status']}); no se encola otro (--singleton).")
				return

		# Un job sobrevive a los reinicios; /tmp no (incidente 2026-09-26: un piloto
		# con su árbol en el scratchpad de /tmp acabó FRUSTRATED tras un reboot).
		volatile = _volatile_paths(payload)
		if volatile and not getattr(args, "allow_tmp", False):
			print(
				f"[ERROR] el payload apunta a rutas volátiles ({', '.join(volatile[:3])}): no sobreviven a un "
				f"reinicio y el job sí. Usa una ruta persistente (p.ej. ~/.local/share/red-pill/…) o --allow-tmp si es deliberado."
			)
			return

		# Validar AQUÍ: un payload malformado debe morir al encolar, no tres
		# intentos después y FRUSTRATED de madrugada.
		from red_pill.jobs.drivers import get_driver_class

		driver_cls = get_driver_class(source)
		if driver_cls:
			try:
				driver_cls.validate(payload)
			except ValueError as e:
				print(f"[ERROR] Payload inválido para '{source}': {e}")
				return
			# RFC_JOB_DAG §4.5: expandir las etapas `type: dag` a compounds con las
			# stages de su receta — el job se persiste ya APLANADO (el determinismo
			# del resume no depende de que la receta siga igual en disco).
			expander = getattr(driver_cls, "expand_manifest", None)
			if expander:
				payload = expander(payload)
		# Resolver el padre a su UUID COMPLETO: las comparaciones del DAG (desbloqueo
		# y cascada de cancelación) van contra `parent_task_id` exacto — guardar un
		# prefijo corto dejaba hijos BLOCKED eternos (bug 2026-09-23).
		if parent:
			parent_task = _find_job(queue, parent)
			if not parent_task:
				print(f"[ERROR] --parent '{parent}' no encontrado (usa el id completo o un prefijo corto válido).")
				return
			parent = parent_task["id"]

		try:
			job_id = queue.enqueue_task(source=source, payload=payload, priority=priority, parent_task_id=parent, mission_id=mission)
		except ValueError as e:
			print(f"[ERROR] {e}")
			return
		if parent:
			if (queue.get_task(job_id) or {}).get("status") == "PENDING":
				print(f"[OK] Job {job_id} encolado (padre {parent[:8]} ya completado: arranca directo).")
			else:
				print(f"[OK] Job {job_id} encolado como BLOCKED (se desbloquea al completar {parent[:8]}).")
		elif getattr(args, "paused", False):
			# Nace PAUSADO: el runner no lo toca hasta `job resume` (encolado en
			# frío para lanzar a mano cuando toque).
			queue.pause_task(job_id)
			print(f"[OK] Job {job_id} encolado PAUSADO (source={source}, priority={priority}). Lánzalo con: red-pill job resume {job_id[:8]}")
		else:
			mission_note = f", mission={mission}" if mission else ""
			print(f"[OK] Job {job_id} encolado (source={source}, priority={priority}{mission_note}).")
		if getattr(args, "kick", False):
			_kick_queue()

	elif args.job_cmd == "list":
		statuses = ["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED", "FRUSTRATED", "COMPLETED"] if args.all else None
		tasks = queue.list_tasks(statuses=statuses, mission_id=getattr(args, "mission", None))
		if getattr(args, "json", False):
			# JOB-001: salida estructurada para parseo agéntico directo
			print(_json.dumps(tasks, ensure_ascii=False, indent=1, default=str))
			return
		if not tasks:
			print("Cola vacía.")
			return
		print(f"{'ID':<10} {'SOURCE':<20} {'STATUS':<12} {'PRIO':<5} {'ATT':<4} {'MISSION':<10} {'PROGRESS':<24} TITLE")
		for t in tasks:
			# El asterisco marca una interrupción dura previa (kill o timeout):
			# reanudable con el mismo verbo, pero la limpieza no está garantizada.
			status = f"{t['status']}*" if t.get("dirty_kill") else t["status"]
			print(
				f"{t['id'][:8]:<10} {t['source'][:19]:<20} {status:<12} {t['priority']:<5} {t['attempts']:<4} {(t.get('mission_id') or '-')[:9]:<10} {_format_progress(_progress_display(t)):<24} {t.get('title') or '-'}"
			)

	elif args.job_cmd == "status":
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		_print_measurements(task)
		task["file_progress"] = _read_job_progress_safe(task.get("id") or "")
		print(_json.dumps(task, indent=2, ensure_ascii=False, default=str))

	elif args.job_cmd in ("pause", "resume"):
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		if args.job_cmd == "pause":
			if queue.pause_task(task["id"]):
				updated = queue.get_task(task["id"])
				st = updated["status"] if updated else "PAUSED"
				if st == "PAUSED":
					print(f"[OK] Job {task['id'][:8]} pausado (PAUSED).")
				else:
					print(
						f"[OK] Solicitud de pausa registrada para Job {task['id'][:8]} (PAUSING). Se pausará al finalizar el step actual (usa 'job resume' para cancelar)."
					)
			else:
				print(f"[WARN] Job {task['id'][:8]} en estado '{task['status']}': transición a pausa no aplicable.")
		else:
			prev_st = task.get("status")
			if queue.resume_task(task["id"]):
				updated = queue.get_task(task["id"])
				st = updated["status"] if updated else "PENDING"
				if prev_st == "PAUSING" and st == "PROCESSING":
					print(f"[OK] Pausa cancelada para Job {task['id'][:8]}. El job continuará ejecutándose en PROCESSING.")
				else:
					print(f"[OK] Job {task['id'][:8]} reanudado (PENDING).")
			else:
				print(f"[WARN] Job {task['id'][:8]} en estado '{task['status']}': reanudación no aplicable.")

	elif args.job_cmd == "skip":
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		if queue.skip_next_task(task["id"]):
			updated = queue.get_task(task["id"])
			st = updated["status"] if updated else task["status"]
			if st == "PENDING":
				print(f"[OK] Job {task['id'][:8]}: siguiente step marcado para saltar (skip_next). El runner lo retoma y avanza sin reintentar.")
			else:
				print(f"[OK] Job {task['id'][:8]} en '{st}': skip_next marcado. Se consumirá en la frontera del próximo step.")
		else:
			print(f"[WARN] Job {task['id'][:8]} no encontrado o sin checkpoint aplicable.")

	elif args.job_cmd == "kill":
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		_kill_job(queue, task, discard=args.discard)

	elif args.job_cmd == "cancel":
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		# Cancelación limpia (sin marca de kill sucio en PENDING/BLOCKED) y con
		# cascada a hijos BLOCKED: equivalente a `kill --discard`.
		_kill_job(queue, task, discard=True)

	elif args.job_cmd == "logs":
		task = _find_job(queue, args.job_id)
		if not task:
			print(f"[ERROR] Job '{args.job_id}' no encontrado.")
			return
		from red_pill.jobs.drivers import job_log_path

		log_path = job_log_path(task["id"])
		if not log_path.exists():
			print(f"[INFO] Sin log todavía para {task['id'][:8]} ({log_path}).")
			return
		lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
		print("\n".join(lines[-args.tail :]))

	elif args.job_cmd == "purge":
		_purge_jobs(queue, args)

	elif args.job_cmd == "process-queue":
		_run_job_queue(queue)
	elif args.job_cmd == "kick":
		_kick_queue()
	else:
		print("Uso: red-pill job {submit|list|status|pause|resume|skip|kill|cancel|logs|purge|process-queue|kick}")


def _kick_queue() -> None:
	"""Dispara el runner de cola AHORA (sin esperar al timer de 1 min).

	Vía oficial: `systemctl --user start --no-block redpill-queue.service` — el
	oneshot corre desatendido con OOM shield e inhibit del sueño, igual que el
	timer. `--no-block` devuelve al instante. Si otro runner ya está activo, el
	flock del worker lo hace ceder (exit 0) sin daño.
	"""
	try:
		subprocess.run(
			["systemctl", "--user", "start", "--no-block", "redpill-queue.service"],
			capture_output=True,
			text=True,
			timeout=15,
		)
	except (subprocess.SubprocessError, OSError) as e:
		print(f"[WARN] no se pudo disparar el runner al momento: {e} (el timer lo recogerá en ≤1 min)")
		return
	print("[OK] Runner disparado — la cola se procesará al momento.")


def _print_measurements(task: dict) -> None:
	"""Lo medido, en cristiano y antes del volcado JSON.

	La cadencia de checkpoint es el dato que decide si un job puede ceder la GPU:
	es el trabajo máximo que se pierde al interrumpirlo. Medida, no supuesta.
	"""
	from red_pill.jobs.drivers import compute_step_timeout, human_duration

	progress = task.get("progress") or {}
	if not isinstance(progress, dict) or not progress:
		return

	lines = [f"  progreso        : {_format_progress(progress)}"]
	if progress.get("step_seconds_ema"):
		lines.append(
			f"  duración media  : {human_duration(progress['step_seconds_ema'])} por step (último: {human_duration(progress.get('step_seconds_last', 0))})"
		)
		bound = compute_step_timeout(task.get("payload") or {}, progress, task.get("attempts", 0))
		lines.append(f"  cota del próximo: {human_duration(bound)}")

	cadence = progress.get("checkpoint_interval_s")
	if cadence:
		target = int(cfg.JOB_CHECKPOINT_CADENCE_TARGET)
		verdict = (
			"dentro del objetivo" if cadence <= target else f"POR ENCIMA del objetivo ({human_duration(target)}) — trabajo en riesgo si se interrumpe"
		)
		lines.append(
			f"  cadencia real   : guarda cada {human_duration(cadence)} ({progress.get('checkpoint_writes_in_step', 0)} por step) → {verdict}"
		)

	print("\n".join(lines) + "\n")


def _read_job_progress_safe(job_id: str) -> Optional[Dict[str, Any]]:
	try:
		from red_pill.core.progress import read_job_progress

		return read_job_progress(job_id)
	except Exception:
		return None


def _progress_display(task: dict) -> dict:
	"""Progreso a mostrar: el de la DB + (si PROCESSING) el avance fino del fichero.

	El fichero (RFC-JOBDAG-002 Fase 4) lo escribe el propio job **fuera de la DB**;
	para los PROCESSING se fusiona como `stage_*` ("· <label> k/N") y queda como
	forense. Nunca bloquea ni rompe el listado (best-effort).
	"""
	prog = dict(task.get("progress") or {})
	if task.get("status") == "PROCESSING":
		fp = _read_job_progress_safe(task.get("id") or "")
		if isinstance(fp, dict):
			if fp.get("label") is not None:
				prog["stage_label"] = fp["label"]
			if fp.get("current") is not None:
				prog["stage_current"] = fp["current"]
			if fp.get("total") is not None:
				prog["stage_total"] = fp["total"]
	return prog


def _format_progress(progress) -> str:
	"""Progreso honesto: contador solo cuando lo hay; fase/item cuando se declara.

	El avance **fino** del fichero de control (Fase 4) llega como `stage_*` y debe
	verse AUNQUE la DB no tenga `current` todavía (etapa larga en su primer step).
	"""
	if not isinstance(progress, dict) or not progress:
		return "-"

	current = progress.get("current")
	total = progress.get("total")
	if current is None:
		current, total = progress.get("current_step"), progress.get("total_steps")

	text = ""
	if current is not None:
		text = f"{current}/{total}" if total else str(current)
		if progress.get("percent") is not None:
			text += f" ({progress['percent']}%)"
	if progress.get("stage_current") is not None:
		segment = f"{progress.get('stage_label', 'fase')} {progress['stage_current']}/{progress.get('stage_total')}"
		text = f"{text} · {segment}" if text else segment
	if progress.get("eta_seconds"):
		text += f" ~{round(progress['eta_seconds'] / 60)}m"
	return text or "-"


def _kill_job(queue, task: dict, discard: bool = False) -> None:
	"""Interrupción dura: sellar el estado ANTES de abatir el scope.

	Ese orden es lo que impide que el runner confunda el kill del operador con
	un fallo del job y le queme un intento del disyuntor.
	"""
	job_id = task["id"]
	if not queue.kill_task(job_id, discard=discard):
		print(f"[WARN] Job {job_id[:8]} en estado '{task['status']}': no se puede abatir.")
		return

	short = job_id[:8]
	# Abatir TODOS los scopes del job por PREFIJO: el element_job usa
	# `redpill-job-<short>` y el CommandMinion del DAG `redpill-job-<short>-<uniq>`
	# (varias etapas por step). Parar solo el exacto dejaba huérfanos (SHARD-15).
	units: list = []
	try:
		listed = subprocess.run(
			["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", f"redpill-job-{short}*"],
			capture_output=True,
			text=True,
			timeout=10,
		)
		units = [ln.split()[0] for ln in listed.stdout.splitlines() if ln.strip()]
	except Exception:
		units = []
	if not units:
		units = [f"redpill-job-{short}.scope"]  # fallback: intentar el exacto
	stopped: list = []
	for unit in units:
		try:
			if subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, text=True, timeout=30).returncode == 0:
				stopped.append(unit)
		except Exception:
			pass

	destino = "FRUSTRATED (descartado)" if discard else "PAUSED* (reanudable con `job resume`)"
	print(f"[OK] Job {short} → {destino}.")
	print(f"     Scopes abatidos: {', '.join(stopped) if stopped else 'ninguno activo'}.")


def _purge_jobs(queue, args: argparse.Namespace) -> None:
	"""Retirar filas terminales de la cola: por id(s) o barrido `--terminal`.

	Se pide confirmación (o `--yes`) porque borrar una fila FRUSTRATED borra
	también su motivo — el forense se hace antes de purgar, no después.
	"""
	if not args.job_ids and not args.terminal:
		print("[ERROR] indica uno o más ids, o --terminal para barrer FRUSTRATED y COMPLETED.")
		return

	if args.terminal:
		candidates = queue.list_tasks(statuses=["FRUSTRATED", "COMPLETED"], limit=500)
		if not candidates:
			print("Nada que purgar: no hay jobs FRUSTRATED ni COMPLETED.")
			return
		print(f"Se retirarán {len(candidates)} job(s) terminales:")
		for t in candidates:
			print(f"  {t['id'][:8]}  {t['source'][:19]:<20} {t['status']:<11} {t.get('title') or '-'}")
		if not args.yes and not _confirm("¿Confirmar purga?"):
			print("Purga cancelada.")
			return
		print(f"[OK] {queue.purge_terminal()} job(s) retirados de la cola.")
		return

	for ref in args.job_ids:
		task = _find_job(queue, ref)
		if not task:
			print(f"[ERROR] Job '{ref}' no encontrado.")
			continue
		if not args.yes and not _confirm(f"¿Retirar {task['id'][:8]} ({task['status']}, {task.get('title') or task['source']})?"):
			print(f"[SKIP] Job {task['id'][:8]} conservado.")
			continue
		if queue.purge_task(task["id"], force=args.force):
			print(f"[OK] Job {task['id'][:8]} retirado de la cola.")
		else:
			hint = " — PAUSED requiere --force" if task["status"] == "PAUSED" else " — solo FRUSTRATED/COMPLETED (PAUSED con --force)"
			print(f"[WARN] Job {task['id'][:8]} en estado '{task['status']}': no purgable{hint}.")


def _confirm(question: str) -> bool:
	"""Confirmación interactiva y-slash-N; cualquier cosa que no sea sí es no."""
	try:
		return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sí")
	except EOFError:
		return False


def _find_job(queue, job_ref: str):
	"""Resuelve un job por id completo o prefijo corto (el que muestra `job list`)."""
	task = queue.get_task(job_ref)
	if task:
		return task
	with queue._get_connection() as conn:
		rows = conn.execute("SELECT id FROM cognitive_tasks WHERE id LIKE ?", (f"{job_ref}%",)).fetchall()
	if len(rows) == 1:
		return queue.get_task(rows[0]["id"])
	return None


def _run_job_queue(queue) -> None:
	"""Runner shot-and-forget (el run-lock R6 vive dentro de process_driver_jobs)."""
	from red_pill.core.queue_worker import process_driver_jobs

	completed = process_driver_jobs(queue)
	print(f"[JOB] Cola procesada. {completed} job(s) completados. Apagando.")
