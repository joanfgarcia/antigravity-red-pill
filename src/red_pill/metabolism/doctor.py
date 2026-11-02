"""
red-pill doctor — synchronous, on-demand config↔runtime health verification.

Sentinel runs continuously in the background (rituals). This is its SYNCHRONOUS
counterpart: run it right after an install/update (or by hand) for an immediate
verdict that what is CONFIGURED matches what is RUNNING. Closes the gap where
`bunker_update()` applied changes but never verified the result (the cause of
post-update breakage: wrong LLM model, swapped ports, dead daemons, undefined timers).

Reuses the existing audits (`SentinelAuditor.audit_runtime` + `audit_vitals` → the
sentinel plugins reconcile daemons/ports/LLM/Qdrant/neon and auto-heal) and adds two
on-demand checks the background flow doesn't frame as "verify":
- expected `redpill-*.timer` units present AND active,
- loaded LLM model matches the configured MINION_DEFAULT_PROFILE (fallback legacy MINION_PROFILE).

`run_doctor()` returns 0 if green/yellow (operational, warnings tolerated), 1 if red
(something is broken) — usable as an install/update gate.

NOTE: the doctor runs the sentinel plugins in AUDIT-ONLY mode (no auto-heal) so it
reports the HONEST current state. Healing is the healer's job (auto_heal_ritual); a
verifier that healed-then-reported would hide a heal that "ran" but didn't fix —
a false GREEN, exactly the failure mode this exists to prevent.
"""

import logging
import os
import subprocess
import time
from datetime import datetime, timezone

logger = logging.getLogger("redpill.doctor")


def _as_epoch(value) -> float | None:
	"""Normaliza `created_at` a epoch.

	neon-link escribe el outbox con la marca nativa de SQLite
	('2026-11-01 20:27:13', TEXT en UTC), pero versiones antiguas guardaron
	epoch REAL. Se aceptan ambos; `None` si el formato es desconocido (el
	llamante decide, nunca revienta).
	"""
	if value is None:
		return None
	if isinstance(value, (int, float)):
		return float(value)
	text = str(value).strip()
	if not text:
		return None
	try:
		return float(text)
	except ValueError:
		pass
	for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
		try:
			return datetime.strptime(text[:26], fmt).replace(tzinfo=timezone.utc).timestamp()
		except ValueError:
			continue
	try:
		return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
	except ValueError:
		return None


def _check_timers() -> list:
	"""Expected redpill-*.timer units present AND active. Catches 'timers sin definir'."""
	out: list = []
	try:
		res = subprocess.run(
			["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "redpill-*.timer"],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=15,
		)
		rows = [ln.split() for ln in res.stdout.splitlines() if ln.strip().startswith("redpill-")]
		if not rows:
			out.append(("red", "No hay timers redpill-*.timer instalados (¿schedule_pulse no corrió?)."))
		else:
			for parts in rows:
				unit = parts[0]
				active = parts[2] if len(parts) > 2 else "?"
				if active != "active":
					out.append(("red", f"Timer {unit} no está active (estado: {active})."))
	except Exception as exc:
		out.append(("yellow", f"No se pudieron verificar los timers: {exc}"))
	return out


def _check_model_match() -> list:
	"""Loaded LLM model == configured MINION_DEFAULT_PROFILE. Best-effort; incertidumbre → info, nunca red."""
	out: list = []
	try:
		from red_pill.core.model_registry import ModelRegistry

		profile_name = os.getenv("MINION_DEFAULT_PROFILE") or os.getenv("MINION_PROFILE")
		configured = bool(profile_name)
		profile_name = profile_name or "samantha"
		model_path = (ModelRegistry.get_profile(profile_name) or {}).get("model_path")
		if not model_path:
			out.append(("yellow", f"No se pudo resolver el modelo del perfil '{profile_name}' (revisar model_profiles.yaml)."))
			return out
		model_file = os.path.basename(str(model_path))

		# Check if native llama-server is running
		ps = subprocess.run(["pgrep", "-af", "llama-server"], stdout=subprocess.PIPE, text=True, timeout=10)
		running = ps.stdout.strip()

		# Check if python dual-bind daemon is running
		ps_py = subprocess.run(["pgrep", "-af", "run_dual_bind.py"], stdout=subprocess.PIPE, text=True, timeout=10)
		running_py = ps_py.stdout.strip()

		if not running and not running_py:
			out.append(("info", f"Perfil configurado: '{profile_name}' ({model_file}); no hay servidor LLM activo — N/A."))
		elif running_py:
			# Query uvicorn endpoint to find the loaded model
			import json
			import urllib.request

			try:
				resp = urllib.request.urlopen("http://127.0.0.1:8760/v1/models", timeout=30)
				data = json.loads(resp.read().decode())
				entry = (data.get("data") or [{}])[0]
				loaded_model = os.path.basename(entry.get("id", ""))
				resident = entry.get("loaded")
				if not loaded_model:
					out.append(("yellow", "No se pudo recuperar el ID del modelo desde la API local."))
				elif resident is False:
					# El proxy carga modelos on-demand: "no residente" no es un mismatch,
					# es el estado normal entre turnos.
					out.append(("info", f"Perfil configurado: '{profile_name}' ({model_file}); el proxy no tiene modelo residente (carga on-demand)."))
				elif model_file == loaded_model:
					out.append(("info", f"Perfil configurado: '{profile_name}' ({model_file}) cargado y activo."))
				elif not configured:
					# Sin MINION_PROFILE explícito comparamos contra un default asumido:
					# eso es incertidumbre, no un fallo de configuración.
					out.append(
						(
							"yellow",
							f"Modelo residente '{loaded_model}' ≠ perfil por defecto '{profile_name}' ({model_file});"
							" define MINION_PROFILE si quieres que el doctor lo exija.",
						)
					)
				else:
					out.append(
						(
							"red",
							f"Modelo en ejecución NO coincide con el configurado (activo: '{loaded_model}', perfil '{profile_name}' → {model_file}).",
						)
					)
			except Exception as exc:
				out.append(("yellow", f"Servidor dual-bind running pero no responde en puerto 8760: {exc}"))
		elif running:
			if model_file not in running:
				out.append(("red", f"Modelo en ejecución NO coincide con el configurado (perfil '{profile_name}' → {model_file})."))
	except Exception as exc:
		out.append(("yellow", f"No se pudo verificar modelo↔config: {exc}"))
	return out


def _audit_plugins_no_heal() -> list:
	"""Run sentinel plugins in AUDIT-ONLY mode (no heal) → honest current state.

	`SentinelAuditor.audit_vitals()` heals AND suppresses healed findings, so a verifier
	built on it reports false-GREEN when a heal ran but didn't fix. Here we call only
	`plugin.audit()`. Returns [(type, severity, first_line), ...]."""
	out: list = []
	try:
		import importlib
		import inspect
		import pkgutil

		import red_pill.config as cfg
		import red_pill.metabolism.sentinel_plugins as plugins_pkg
		from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

		config = cfg.get_config()
		for _, name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
			module = importlib.import_module(f"red_pill.metabolism.sentinel_plugins.{name}")
			for _, obj in inspect.getmembers(module, inspect.isclass):
				if issubclass(obj, SentinelPlugin) and obj is not SentinelPlugin and not inspect.isabstract(obj):
					plugin = obj()
					try:
						if not plugin.is_enabled(config):
							continue
						for f in plugin.audit(config) or []:
							line = f.message.splitlines()[0] if f.message else f.type
							out.append((f.type, f.severity, line))
					except Exception as exc:
						out.append(("plugin_crash", 10.0, f"Plugin {getattr(plugin, 'name', name)} CRASHED en audit: {exc}"))
	except Exception as exc:
		out.append(("plugin_load", 7.0, f"No se pudieron cargar los plugins de Sentinel: {exc}"))
	return out


def _check_coro() -> list:
	"""Checks de la mensajería interna: recibos, hooks, outbox y versión de neon-link.

	Cubre la deuda operativa de S2: una migración a medias, un hook viejo que ya no
	acusa, un outbox soul atascado o un reconcile que se quedó atrás. No cura: dice
	dónde mirar.
	"""
	out: list = []
	# 1) Esquema de recibos y migración de event_deliveries.
	try:
		import sqlite3

		from red_pill.core.paths import get_session_db

		db = get_session_db()
		if db.exists():
			con = sqlite3.connect(str(db), timeout=2.0)
			try:
				tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
				if "event_deliveries" in tables:
					out.append(("yellow", "event_deliveries sigue en session.db: ejecuta `red-pill coro reconcile` o reinicia el kernel para migrar a message_receipts."))
				if "message_receipts" not in tables:
					out.append(("yellow", "message_receipts no existe: el kernel aún no ha migrado los recibos."))
				elif "mailbox_reconcile_state" in tables:
					state = con.execute(
						"SELECT last_seq FROM mailbox_reconcile_state WHERE id = 'outbox'"
					).fetchone()
					if state is not None:
						last = int(state[0])
						n = con.execute(
							"SELECT COUNT(*) FROM mission_events e"
							" LEFT JOIN message_receipts r ON r.event_id = e.event_id AND r.continuity_id = e.to_continuity"
							" WHERE e.event_seq > ? AND e.to_continuity IS NOT NULL"
							" AND e.verb IN ('notify','ask','reply') AND e.sealed = 0"
							" AND r.event_id IS NULL",
							(last,),
						).fetchone()[0]
						if n:
							out.append(("yellow", f"{n} mensaje(s) dirigidos sin recibo tras la marca de agua: el reconciliador va atrasado (red-pill coro reconcile)."))
			finally:
				con.close()
	except Exception as exc:
		out.append(("info", f"No se pudo revisar el esquema del coro: {exc}"))

	# 2) versión mínima de neon-link (canal soul).
	try:
		from importlib.metadata import version

		raw = version("neon-link")
		parts = tuple(int(x) for x in raw.split(".")[:2])
		if parts < (0, 7):
			out.append(("red", f"neon-link {raw} < 0.7.0: no tiene canal soul. Actualiza la dependencia."))
		else:
			out.append(("info", f"neon-link {raw}: canal soul disponible."))
	except Exception as exc:
		out.append(("yellow", f"No se pudo resolver la versión de neon-link: {exc}"))

	# 3) hooks instalados: si son viejos, el acuse se pierde en silencio.
	from red_pill.core.paths import get_harness_config_path

	for path, label in (
		(get_harness_config_path("opencode", "plugins", "redpill-scribe.js"), "opencode"),
		(get_harness_config_path("claude", "hooks", "redpill_turn_start.py"), "claude"),
	):
		try:
			if path.exists() and "message_receipts" not in path.read_text(encoding="utf-8", errors="replace"):
				out.append(("red", f"hook {label} desactualizado ({path}): no escribe message_receipts; reseed el arnés."))
		except Exception as exc:
			out.append(("info", f"No se pudo leer el hook {label}: {exc}"))

	# 4) outbox soul: atascos y DLQ. Cada consulta va aislada: una tabla ausente o
	# un `created_at` con formato inesperado no pueden cegar el resto del chequeo.
	try:
		import sqlite3

		from red_pill.core.paths import get_neon_link_db_path

		db = get_neon_link_db_path()
		if db.exists():
			con = sqlite3.connect(str(db), timeout=2.0)
			con.row_factory = sqlite3.Row
			try:
				try:
					row = con.execute(
						"SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM outbox WHERE channel='soul' AND status='PENDING'"
					).fetchone()
				except sqlite3.Error as exc:
					out.append(("info", f"No se pudo leer el outbox soul: {exc}"))
					row = None
				if row and row["n"]:
					oldest = _as_epoch(row["oldest"])
					if oldest is None:
						out.append(("info", f"{row['n']} sobre(s) soul PENDING; edad desconocida (created_at ilegible: {row['oldest']!r})."))
					else:
						age = time.time() - oldest
						if age > 3600:
							out.append(("yellow", f"{row['n']} sobre(s) soul PENDING; el más viejo lleva {age/60:.0f} min. Revisa el SoulHub."))
				try:
					dead = con.execute("SELECT COUNT(*) FROM dead_letters WHERE channel='soul'").fetchone()[0]
				except sqlite3.Error as exc:
					out.append(("info", f"No se pudieron leer las dead letters soul: {exc}"))
					dead = 0
				if dead:
					out.append(("yellow", f"{dead} dead letter(s) soul: revisa `neon-link redrive`."))
			finally:
				con.close()
	except Exception as exc:
		out.append(("info", f"No se pudo revisar el outbox soul: {exc}"))
	return out


def run_doctor(quiet: bool = False) -> int:
	"""Run the synchronous health verification. Returns 0 (ok) / 1 (red)."""
	reds: list = []
	yellows: list = []
	infos: list = []

	# 1a. Daemons systemd FALLIDOS + errores de journal (audit_runtime no suprime nada).
	try:
		from red_pill.metabolism.auditor import SentinelAuditor

		for f in SentinelAuditor().audit_runtime().findings:
			line = f.message.splitlines()[0] if f.message else f.type
			(reds if f.severity >= 8.0 else yellows).append(f"[{f.type}] {line}")
	except Exception as exc:
		reds.append(f"audit_runtime CRASHED: {exc}")

	# 1b. Plugins config↔runtime en modo AUDIT-ONLY (estado honesto; sin heal que enmascare).
	for ftype, sev, line in _audit_plugins_no_heal():
		(reds if sev >= 8.0 else yellows).append(f"[{ftype}] {line}")

	# 2. Chequeos on-demand extra (lo que el flujo de fondo no enmarca como "verify").
	buckets = {"red": reds, "yellow": yellows, "info": infos}
	for sev, msg in _check_timers() + _check_model_match() + _check_coro():
		buckets.get(sev, yellows).append(msg)

	status = "red" if reds else ("yellow" if yellows else "green")
	icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[status]
	print(f"\n{icon} red-pill doctor — {status.upper()}  (config ↔ runtime)")
	for m in reds:
		print(f"  ❌ {m}")
	for m in yellows:
		print(f"  ⚠️  {m}")
	if not quiet:
		for m in infos:
			print(f"  ·  {m}")
	if status == "green":
		print("  Todo lo configurado corresponde con lo que está corriendo.")
	return 1 if reds else 0
