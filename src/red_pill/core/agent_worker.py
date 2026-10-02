import contextlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from red_pill.core.inbox_adapters import parse_payload
from red_pill.core.paths import get_config_dir, get_neon_link_config_dir, get_neon_link_db_path, get_state_dir

# Cargar la configuración agnóstica de Neon-Link primero (Single Source of Truth)
neon_link_config = get_neon_link_config_dir() / ".env"
if neon_link_config.exists():
	load_dotenv(neon_link_config)

# Cargar la configuración centralizada de Red-Pill
red_pill_config = get_config_dir() / ".env"
if red_pill_config.exists():
	load_dotenv(red_pill_config)

load_dotenv()  # Override local si existiera

import red_pill.config as cfg  # noqa: E402
from red_pill.core.pulse_strategy import NullPulseStrategy, PulseContext, PulseStrategy, build_pulse_strategy  # noqa: E402
from red_pill.swarm.bridges import (  # noqa: E402
	AgentBridge,  # noqa: E402
	AllModelsExhausted,
	BridgeCapabilities,
	NoModelsConfigured,
	create_cascade_bridge,
)

logger = logging.getLogger(__name__)

# Alineación con el estándar de Sovereign Gateway (Neon-Link)
default_db = get_neon_link_db_path()
DB_PATH = Path(os.environ.get("NEON_LINK_DB_PATH", default_db))


# Budget guard defaults
MAX_AWAKENINGS_PER_DAY = 8
AWAKENING_MAX_TOOL_CALLS = 40
# AWAKENING_TIMEOUT es configurable (A-5): cfg.get_config().AWAKENING_TIMEOUT

# Derecho al Silencio (AWAKEN-002): la directiva del despertar pide responder
# ÚNICAMENTE con la frase canónica ("Ejercicio consciente del Derecho al
# Silencio. Estado del Búnker: calma.", 71 caracteres).
SILENCE_PHRASE = "Ejercicio consciente del Derecho al Silencio"
# Medido sobre los datos reales del operador (163 despertares de opencode
# recuperados cruzando `execution_ledger` con opencode.db): 61 silencios de
# 71-1017 caracteres y 30-167 s; 102 productivos de 369-2123 caracteres que
# NUNCA citan la frase. Los silencios llegan con tres formas:
#   - la frase sola (71 car.);
#   - narración intermedia + la frase como bloque final: el bridge de opencode
#     concatena con "".join todas las partes de texto del asistente, así que
#     «…lo registro y ejerzo silencio.» y la frase llegan pegadas;
#   - la frase + una nota de estado breve (247-369 car.).
# De ahí las dos vías de `is_silence_response`: la respuesta TERMINA con la frase
# (más la cola opcional "Estado del Búnker: <estado>"), o EMPIEZA por ella y mide
# menos de SILENCE_MAX_CHARS. Un informe que solo la cita a mitad de texto no
# cumple ninguna de las dos.
SILENCE_MAX_CHARS = 400
# Cola admitida tras la frase: puntuación, la coletilla de estado del Búnker (el
# modelo escribe Búnker/Bünker/Bunker) y cierres de cita/énfasis markdown.
_SILENCE_TAIL_RE = re.compile(
	r"[\s.,;:!¡]*(?:estado\s+del\s+b[uúü]nker\s*:\s*[^\n.!?]{1,30}?)?[\s.,;:!'\"`*_»”’)]*",
)
_SILENCE_LEAD_CHARS = "'\"`*_>«“‘( "

# Zonas del desk que un despertar puede tocar. "planner" = ideas/research/design/
# pending/in_progress; "awakening" = solo logs de despertar; "none" = nada.
_PLANNER_ZONES = {
	"ideas": "planner/ideas",
	"research": "planner/research",
	"design": "planner/design",
	"pending": "planner/pending",
	"in_progress": "planner/in_progress",
	"awakening": "awakening",
}


def is_silence_response(text: str) -> bool:
	"""True si la respuesta ejerce el Derecho al Silencio (AWAKEN-002).

	Dos vías (ver el comentario de SILENCE_PHRASE para las medidas reales):
	a) TERMINA con la frase canónica, tolerando la cola "Estado del Búnker:
	<estado>", puntuación final, comillas y énfasis markdown — cubre la
	narración intermedia que el bridge pega delante de la frase;
	b) EMPIEZA por la frase y mide menos de SILENCE_MAX_CHARS — la frase más una
	nota de estado breve.
	Un informe productivo que solo CITA la frase a mitad de texto no es silencio:
	se entrega y consume tope como cualquier despertar productivo. Fuente única
	para el despertar, la respuesta de Telegram y el pulse del plugin."""
	body = unicodedata.normalize("NFC", text or "").strip().casefold()
	if not body:
		return False
	phrase = SILENCE_PHRASE.casefold()
	cut = body.rfind(phrase)
	if cut < 0:
		return False
	if _SILENCE_TAIL_RE.fullmatch(body[cut + len(phrase) :]):
		return True
	return len(body) < SILENCE_MAX_CHARS and body.lstrip(_SILENCE_LEAD_CHARS).startswith(phrase)


def _handshake_step(user_prompt: str, mode: str) -> str:
	"""Identity-loading step, named by the RedPill-Kernel MCP tool itself (each
	client may prefix MCP tool names its own way; the core never spells a
	client-specific name). `sovereign_handshake` with is_new_session=true loads
	the identity from the Bünker and runs the interceptor pipeline in one call."""
	return (
		f"Call the RedPill-Kernel MCP tool `sovereign_handshake` with user_prompt={user_prompt}, "
		f'is_new_session=true and mode="{mode}" — it loads your identity from the Bünker.'
	)


def _awakening_planner_directive(policy: str) -> str:
	"""Construye el bloque de política de contribución al desk para el despertar.

	`policy` es la cadena `AWAKENING_PLANNER_ACCESS` del .env (lista separada por
	comas, o "planner"/"none"). Devuelve la directiva que se inyecta en el prompt
	headless. El agente solo contribuye a las zonas declaradas por el operador.
	"""
	zones: list[str] = []
	raw = (policy or "planner").strip().lower()
	if raw == "none":
		return (
			"DESK POLICY: No toques el desk (${AGENT_CORE_DIR}). "
			"Puedes leer el panel (planner/tools/panel.py) para informarte, "
			"pero no contribuyas a ideas/, pending/ ni ninguna zona de planificación. "
			"Registra tu despertar en el log (directiva 1) y nada más."
		)
	if raw == "planner":
		zones = sorted(_PLANNER_ZONES.keys())
	else:
		for part in raw.split(","):
			part = part.strip()
			if part in _PLANNER_ZONES:
				zones.append(part)
	zones = sorted(set(zones))
	if not zones:
		return _awakening_planner_directive("none")

	paths = ", ".join(f"`{_PLANNER_ZONES[z]}/`" for z in zones)
	return (
		f"DESK POLICY (configurada por tu operador): puedes contribuir al desk en estas "
		f"zonas de planificación: {paths}. "
		f"Antes de contribuir, lee `planner/README.md` (el modelo: fase = carpeta, flujo "
		f"blando) y el README de la fase que vayas a tocar. "
		f"Solo toca ideas/pending/README.md para añadir una chispa/tarea nueva o mover "
		f"una a otra fase con `git mv`; NO edites docs de otras fases sin necesidad. "
		f"Registra en tu log de despertar qué contribución hiciste. Si esa contribución "
		f"avanza un RFC de proyecto, anota TAMBIÉN en el propio RFC la rama + ruta del "
		f"worktree + último commit, para que el siguiente despertar retome el hilo."
	)


def _awakening_channel_directive(operator: str | None = None) -> str:
	"""Bloque delgado (AWAKEN-002): canal de notas + puntero al índice del desk.

	Patrón deliberado: el prompt NO lleva la directiva entera de vigilancia; lleva
	el buzón (direcciones 1 y 3) y un puntero al índice AWAKEN-002 que el despertar
	lee solo si le apetece. Nunca lanza: si el desk no está, devuelve el puntero.
	"""
	pointer = (
		"CANAL DE NOTAS Y TIEMPO LIBRE (AWAKEN-002, opcional — NADA obligatorio):\n"
		"PRIMER PASO opcional: revisa el buzón `${AGENT_CORE_DIR}/awakening/notes/` "
		"(las notas sin `para:` son deberes del Fixer para ti). Registra `## Leída <ts>` "
		"con estado (hecho / no hecho + porqué / visto) y firma `— <nombre> · <ts>`.\n"
		"Si algo necesita una DECISIÓN del Fixer, déjale una nota `para: <Operador>` en ese "
		"buzón: su próxima sesión la verá en el digest.\n"
		"Índice completo de tu tiempo libre (vigilancia del planner + pre-pase determinista "
		"`scripts/planner_state_audit.py`): `planner/design/AWAKEN-002-despertares-utiles/README.md`."
	)
	try:
		from red_pill.core import awakening_channel as ch

		operator = operator or ch.operator_name()
		pending = ch.count_for_operator(operator=operator)
		duties = len(ch.duty_notes(operator=operator))
	except Exception:
		return pointer
	return f"{pointer}\nRecuento ahora: {pending} nota(s) para {operator} sin leer; {duties} deber(es) sin marcar."


def get_connection():
	# Last line of defence: a test must never open/write the production events.db.
	from red_pill.core.paths import _assert_not_production_dir

	_assert_not_production_dir(DB_PATH, "agent_worker.get_connection() DB_PATH")
	conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA synchronous=NORMAL;")
	# Execution ledger for budget guard
	conn.execute(
		"CREATE TABLE IF NOT EXISTS execution_ledger ("
		"id INTEGER PRIMARY KEY AUTOINCREMENT, "
		"exec_type TEXT NOT NULL, "
		"conversation_id TEXT, "
		"started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
		"duration_s REAL, "
		"response_len INTEGER DEFAULT 0, "
		"status TEXT DEFAULT 'started'"
		")"
	)
	# Migración AWAKEN-002: `counted` distingue los despertares productivos de
	# los que ejercen el Derecho al Silencio (estos no consumen el tope salvo
	# AWAKENING_SILENCE_COUNTS=true). DEFAULT 1 preserva el cómputo previo.
	ledger_cols = {row[1] for row in conn.execute("PRAGMA table_info(execution_ledger)")}
	if "counted" not in ledger_cols:
		try:
			conn.execute("ALTER TABLE execution_ledger ADD COLUMN counted INTEGER DEFAULT 1")
		except sqlite3.OperationalError as e:
			# Carrera entre conexiones (heartbeat + pulse, o dos procesos): otra
			# migró entre el PRAGMA y el ALTER. La columna ya está: nada que hacer.
			if "duplicate column" not in str(e).lower():
				raise
	return conn


def _format_cascade_error(exc: Exception) -> str:
	"""Build a user-facing Telegram message for an exhausted bridge cascade."""
	if isinstance(exc, NoModelsConfigured):
		return "⚠️ No hay ningún modelo configurado para atender el mensaje (TELEGRAM_BRIDGE_CASCADE vacío)."
	errors = getattr(exc, "errors", None)
	if errors:
		lines = "\n".join(f"• {t.backend}/{t.model or 'default'}: {msg}" for t, msg in errors)
		return f"⚠️ No pude atender tu mensaje — ningún modelo disponible:\n{lines}"
	return f"⚠️ No pude atender tu mensaje: {exc}"


def _is_bridge_timeout(exc: Exception) -> bool:
	"""Classify a bridge failure as a TIMEOUT (D24).

	Bridge backends surface timeouts as `RuntimeError("... timed out after Ns")`
	(raised from `subprocess.TimeoutExpired`). Anything else — spawn failures,
	network errors, 5xx, quota messages — is transient, NOT a timeout.
	"""
	import subprocess

	if isinstance(exc, subprocess.TimeoutExpired):
		return True
	text = str(exc).lower()
	return isinstance(exc, RuntimeError) and ("timed out" in text or "timeout" in text)


def _emit_pain_signal_once(name: str, *, source: str, originator: str, message: str) -> None:
	"""Inject a WARNING pain signal unless one with the same name is already
	active (dedup via has_signal: the oneshot worker runs every minute). Never raises."""
	try:
		from red_pill.memory import MemoryManager

		mm = MemoryManager()
		if mm.has_signal(name):
			return
		mm.inject_signal(
			name=name,
			intensity=6.0,
			signal_type="pain",
			source=source,
			originator=originator,
			criticality="WARNING",
			message=message,
		)
	except Exception as e:
		logger.warning(f"[IDEWorker] Failed to emit pain signal {name}: {e}")


def _emit_d24_pain_signal(msg_ids, error_text: str) -> None:
	"""D24 req. operador: if a timeout is NOT classified as such (and thus retried
	with cap 3 instead of cap 1), emit a typed pain signal so someone investigates."""
	_emit_pain_signal_once(
		"telegram_timeout_cap1_not_applied",
		source="TelegramWorker",
		originator="worker._process_via_bridge",
		message=f"Timeout del bridge clasificado como transitorio (cap 3 en vez de cap 1). msgs={msg_ids}. error={error_text[:300]}",
	)


def _detect_routing_keyword(text: str) -> Optional[str]:
	"""Detect an explicit routing keyword at the START of a Telegram message
	(D2/D10). Case-insensitive, first token. In Fase 1 this is signal-only:
	the keyword is stripped from the prompt (D10) but execution stays fast path
	(forward-compatible with Fase 2's heavy path).

	Returns the matched keyword ('/mission', '#mission', '#heavy', '#job') or None.
	"""
	if not text:
		return None
	first = text.strip().split(maxsplit=1)[0].lower()
	keywords = {"/mission", "#mission", "#heavy", "#job"}
	return next((k for k in keywords if first == k), None)


def _detect_escalate_marker(response: str, window: int = 64) -> bool:
	"""Detect the [ESCALATE] marker at the START of a model response (D14).
	Parsing is tolerant: the marker must appear within the first `window`
	characters (ratified default 64), allowing for whitespace/prefix noise.
	In Fase 1 this is signal-only — the full response is still delivered.
	"""
	if not response:
		return False
	head = response[:window].upper()
	return "[ESCALATE]" in head


def _without_local_unless_allowed(cascade: list, local_allowed: bool) -> list:
	"""D5 (Fase 1 guard): local is not capable of heavy work — filter it out of
	the conversational cascade unless explicitly allowed."""
	if local_allowed or not cascade:
		return cascade
	filtered = [t for t in cascade if t.backend != "local"]
	if len(filtered) != len(cascade):
		logger.info("[IDEWorker] D5 guard: filtered local target(s) from TELEGRAM_BRIDGE_CASCADE")
	return filtered


def _cascade_degradation(cascade: list, caps: Optional[BridgeCapabilities]) -> Optional[str]:
	"""Backend-agnostic degraded-cascade check: a configured cascade is served by
	one of its own targets. If the effective bridge is none of them, every target
	failed to construct and the cascade fell back to something the operator did
	not configure. Returns the reason, or None if the cascade is healthy/absent."""
	configured = sorted({t.backend for t in cascade})
	if not configured:
		return None
	served_by = caps.backend.value if caps else None
	if served_by in configured:
		return None
	return f"TELEGRAM_BRIDGE_CASCADE {configured} could not build any target"


class IDEWorker:
	def __init__(self):
		self.running = True
		self._bridge_telegram: AgentBridge | None = None
		self._bridge_awakening: AgentBridge | None = None
		self._bridge_minion: AgentBridge | None = None
		# Capabilities of the conversational bridge; None until one is built (the
		# core assumes no transport by default).
		self._caps: BridgeCapabilities | None = None
		self._samantha_worker = None
		# AgentBridge: create execution bridges based on config
		try:
			cfg_inst = cfg.get_config()
			telegram_cascade = _without_local_unless_allowed(cfg_inst.TELEGRAM_BRIDGE_CASCADE, cfg_inst.LOCAL_ALLOWED_FOR_HEAVY)
			self._bridge_telegram = create_cascade_bridge(telegram_cascade, name="TELEGRAM_BRIDGE_CASCADE", origin="telegram")
			self._bridge_awakening = create_cascade_bridge(cfg_inst.AWAKENING_BRIDGE_CASCADE, name="AWAKENING_BRIDGE_CASCADE", origin="awakening")
			self._bridge_minion = create_cascade_bridge(cfg_inst.DEFAULT_MINION_BRIDGE_CASCADE, name="DEFAULT_MINION_BRIDGE_CASCADE")

			self._caps = self._bridge_telegram.get_capabilities()
			logger.info(f"[IDEWorker] Telegram Bridge: {self._caps.backend.value.upper()}")
			logger.info(f"[IDEWorker] Awakening Bridge: {self._bridge_awakening.get_capabilities().backend.value.upper()}")
			logger.info(f"[IDEWorker] Minion Bridge: {self._bridge_minion.get_capabilities().backend.value.upper()}")
			degraded_reason = _cascade_degradation(telegram_cascade, self._caps)
		except Exception as e:
			degraded_reason = f"bridge construction failed: {e}"
			self._fall_back_to_default_backend()
		if degraded_reason:
			self._report_degraded_bridges(degraded_reason)
		# SamanthaWorker: background thread for local LLM tasks (non-blocking)
		try:
			from red_pill.inference.samantha_worker import SamanthaWorker

			self._samantha_worker = SamanthaWorker()
			self._samantha_worker.start()
			logger.info("[IDEWorker] SamanthaWorker thread started")
		except Exception as e:
			logger.warning(f"[IDEWorker] SamanthaWorker init failed (local LLM tasks disabled): {e}")

		# D21: decoupled heartbeat thread + activity lease. The main pulse can
		# block on a 300s bridge call; the heartbeat must keep beating DURING it
		# or neon-link (60s threshold) declares a false "Córtex Offline". A dead
		# main loop stops touching the lease → it expires (HEARTBEAT_LEASE) →
		# the thread stops beating → real offline is still detected.
		self._lease_lock = threading.Lock()
		self._lease_touch = time.monotonic()
		self._heartbeat_thread = threading.Thread(
			target=self._heartbeat_thread_main,
			name="heartbeat-daemon",
			daemon=True,
		)
		self._heartbeat_thread.start()
		logger.info("[IDEWorker] Heartbeat thread started (D21, lease=%ss)", cfg.get_config().HEARTBEAT_LEASE)

		# ARCH-001: backend-specific pulse work is delegated to a strategy
		# resolved via the provider-agnostic registry. The core never names a
		# concrete backend.
		self._strategy: PulseStrategy = self._build_strategy()

	def _fall_back_to_default_backend(self) -> None:
		"""Bridge construction failed: degrade to the single configured IDE_BACKEND
		bridge, never to a hardcoded transport. Each bridge is built on its own so
		one failure leaves just that bridge unset (handled downstream) instead of
		killing the worker (and with it the heartbeat). D5 still applies: a local
		backend never serves the conversational path unless explicitly allowed."""
		from red_pill.swarm.bridges.factory import create_bridge

		def _build(backend: str) -> AgentBridge | None:
			try:
				return create_bridge(backend)
			except Exception as e:
				logger.error(f"[IDEWorker] fallback bridge '{backend}' could not be built: {e}")
				return None

		try:
			cfg_inst = cfg.get_config()
		except Exception as e:
			logger.error(f"[IDEWorker] config unreadable — no fallback bridge can be chosen: {e}")
			return
		default_backend = cfg_inst.IDE_BACKEND
		if default_backend == "local" and not cfg_inst.LOCAL_ALLOWED_FOR_HEAVY:
			logger.error("[IDEWorker] D5 guard: IDE_BACKEND=local cannot serve Telegram; conversational bridge left unset")
			self._bridge_telegram = None
		else:
			self._bridge_telegram = _build(default_backend)
		self._bridge_awakening = _build(default_backend)
		self._bridge_minion = _build(default_backend)
		self._caps = self._bridge_telegram.get_capabilities() if self._bridge_telegram else None

	def _report_degraded_bridges(self, reason: str) -> None:
		"""Agnostic degraded-cascade report: the operator configured bridges the
		worker could not build. Logged once per process (the worker is a oneshot
		per minute) plus a deduplicated pain signal."""
		served_by = self._caps.backend.value if self._caps else "none"
		logger.error(f"[IDEWorker] Degraded bridges ({reason}); conversational bridge in use: {served_by}")
		_emit_pain_signal_once(
			"worker_bridge_cascade_degraded",
			source="IDEWorker",
			originator="core.agent_worker.IDEWorker.__init__",
			message=f"El worker no pudo construir los puentes configurados ({reason[:300]}); puente conversacional efectivo: {served_by}.",
		)

	def _build_strategy(self) -> PulseStrategy:
		"""Resolve the backend-specific pulse strategy via the core registry.

		The core does NOT name any backend: `build_pulse_strategy` returns the
		first strategy a plugin's factory accepts for these bridges (or
		NullPulseStrategy if none applies). This keeps `red_pill.core`
		provider-agnostic.
		"""
		strategy = build_pulse_strategy(PulseContext(bridge_minion=self._bridge_minion, capabilities=self._caps))
		if isinstance(strategy, NullPulseStrategy):
			# No backend strategy applied: legitimate for backends without
			# backend-specific pulse work. A plugin that FAILED to load is
			# reported by the registry itself.
			logger.debug("[IDEWorker] no pulse strategy applies; using no-op")
		return strategy

	def _get_connection(self):
		"""Connection helper exposed to pulse strategies (they run SQL directly)."""
		return get_connection()

	def _touch_lease(self):
		"""Record worker activity. The heartbeat thread only beats while the lease
		is fresh — a healthy main loop keeps touching at every pulse boundary and
		before every bridge call."""
		try:
			with self._lease_lock:
				self._lease_touch = time.monotonic()
		except Exception as e:
			logger.debug(f"[IDEWorker] lease touch failed: {e}")

	@contextlib.contextmanager
	def _lease_keeper(self, interval: float | None = None):
		"""D21 (AWAKEN-002 §5): mantiene el lease fresco durante una llamada de
		puente larga (el despertar vigilando el planner). Sin esto, un despertar
		de más de HEARTBEAT_LEASE (900s) hace que el latido enmudezca y neon-link
		declare un falso "Córtex Offline". El keeper solo late mientras vive esta
		sección; si el hilo principal muere, deja de latir y el offline se detecta.
		"""
		stop = threading.Event()
		every = interval if interval is not None else max(20.0, cfg.get_config().HEARTBEAT_LEASE / 3.0)

		def _beat():
			while not stop.wait(every):
				self._touch_lease()

		th = threading.Thread(target=_beat, name="awakening-lease-keeper", daemon=True)
		th.start()
		try:
			yield
		finally:
			stop.set()

	def _heartbeat_thread_main(self):
		"""Daemon thread: update system_health while the process lives and the
		lease is fresh. Falls silent when the main loop is dead (lease expired) so
		real offline is detectable. Uses its own connection to avoid sharing the
		pulse's write transaction (D23)."""
		lease = cfg.get_config().HEARTBEAT_LEASE
		while True:
			try:
				with self._lease_lock:
					fresh = (time.monotonic() - self._lease_touch) < lease
				if fresh:
					self.update_heartbeat()
				time.sleep(20)
			except Exception as e:
				logger.warning(f"[IDEWorker] Heartbeat thread error: {e}")
				time.sleep(20)

	def run(self):
		logger.info("Red-Pill Agent Worker started.")
		while self.running:
			try:
				self.run_once()
				time.sleep(2)
			except KeyboardInterrupt:
				logger.info("Shutting down worker...")
				self.running = False
			except Exception as e:
				logger.error(f"Worker exception: {e}")
				time.sleep(5)

	def run_once(self):
		# D21: touch the heartbeat lease at the start of each pulse — the
		# heartbeat thread only beats while this stays fresh.
		self._touch_lease()
		# Containment: one poisoned inbox item must not kill the pulse (and with
		# it the heartbeat that neon-link watches to report Córtex Offline).
		try:
			self.process_inbox()
		except Exception:
			logger.exception("[IDEWorker] process_inbox failed — pulse continues")
		# Fase 2: entrega de resultados de jobs Telegram (D18/D19) en cada pulse.
		try:
			self._check_telegram_jobs()
		except Exception:
			logger.exception("[IDEWorker] _check_telegram_jobs failed — pulse continues")
		# Backend-specific pulse delegated to the registered strategy: the core
		# stays neutral and the strategy preserves the original behavior exactly.
		try:
			self._strategy.pulse(self)
		except Exception:
			logger.exception("[IDEWorker] backend pulse failed — pulse continues")
		# Generic housekeeping lives in the core so it survives a missing or
		# broken backend plugin. Only a strategy whose path owns the whole tick
		# (legacy IDE polling) declines it.
		if self._core_housekeeping_allowed():
			self._sweep_telegram_sessions()
			# Samantha Queue: signal worker if there are pending tasks (NON-BLOCKING)
			self._signal_samantha_worker()
		# Watchdog: verify SamanthaWorker thread health
		self._watchdog_samantha()
		self.update_heartbeat()

	def _core_housekeeping_allowed(self) -> bool:
		try:
			return bool(self._strategy.allows_core_housekeeping(self))
		except Exception:
			logger.exception("[IDEWorker] strategy housekeeping flag failed — running core housekeeping")
			return True

	def _sweep_telegram_sessions(self):
		"""Janitor sweep for local Telegram sessions (archived conversations)."""
		try:
			from red_pill.telegram.session import TelegramSessionManager

			purged = TelegramSessionManager().run_janitor_sweep()
			if purged > 0:
				logger.info(f"[Janitor] Sweep complete. Purged {purged} archived conversations.")
		except Exception as e:
			logger.error(f"Janitor sweep failed: {e}")

	def update_heartbeat(self):
		conn = get_connection()
		conn.execute("UPDATE system_health SET last_heartbeat = CURRENT_TIMESTAMP WHERE service_name = 'red_pill'")
		conn.commit()
		conn.close()

	def _handle_retry_failure(
		self,
		msg_ids,
		channel,
		channel_user_id,
		cursor,
		exc: Optional[Exception] = None,
		error_text: Optional[str] = None,
	) -> bool:
		"""Increment retries with a cap by error class (D24).

		Timeout → ONE retry allowed: the second timeout is DEAD (the same prompt
		would burn the timeout again, blocking the pulse ~300s more and tripling
		token cost). Transient errors (spawn/red/5xx) → cap 3 as before.

		When the cap is reached: mark inbox DEAD, write the dead_letters row
		(D12), and notify the user via outbox.

		Returns True when the message was killed (DEAD), False otherwise.
		"""
		text = error_text or (str(exc) if exc else "unknown error")
		is_timeout = _is_bridge_timeout(exc) if exc else "timed out" in (text or "").lower()

		# D24 signal de dolor: if the failure LOOKS like a timeout but was NOT
		# classified as one (classifier miss), the cap would wrongly be higher → flag it.
		looks_like_timeout = "timed out" in (text or "").lower() or "timeout" in (text or "").lower()
		if looks_like_timeout and not is_timeout:
			_emit_d24_pain_signal(msg_ids, text)

		# Cap in terms of the retries counter: timeout allows ONE retry (the
		# second timeout → DEAD, so retries>=2 kills it); transients keep the
		# legacy cap 3 (retries>=3 → DEAD). Mirrors diagram 4.5 for transients.
		cap = 2 if is_timeout else 3

		for m_id in msg_ids:
			row = cursor.execute("SELECT retries FROM inbox WHERE id = ?", (m_id,)).fetchone()
			retries = (row["retries"] if row else 0) + 1
			if retries >= cap:
				logger.error(f"[{msg_ids}] Retries exhausted (cap={cap}, class={'timeout' if is_timeout else 'transient'}) for msg {m_id}: {text}")
				cursor.execute("UPDATE inbox SET status = 'DEAD', retries = ? WHERE id = ?", (retries, m_id))
				# D12: write to the dead_letters table (neon-link events.db)
				try:
					orig = cursor.execute("SELECT payload FROM inbox WHERE id = ?", (m_id,)).fetchone()
					payload = orig["payload"] if orig else None
					cursor.execute(
						"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) "
						"VALUES ('inbox', ?, ?, ?, ?, ?)",
						(m_id, channel, channel_user_id, payload, text[:500]),
					)
				except Exception as e:
					logger.warning(f"[{msg_ids}] Failed to write dead_letter for {m_id}: {e}")
				if channel != "system":
					cursor.execute(
						"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
						(
							channel,
							channel_user_id,
							None,
							json.dumps(
								{
									"text": "⚠️ Tu mensaje no pudo ser procesado tras "
									f"{retries} intento(s). Reintenta con /new o revisa la cola con /queue. "
									"Para prompts ambiciosos, considera prefijar con `/mission` o `#mission`."
								}
							),
						),
					)
			else:
				logger.warning(f"[{msg_ids}] Retry {retries}/{cap} for msg {m_id}: {text}")
				cursor.execute("UPDATE inbox SET retries = ? WHERE id = ?", (retries, m_id))
		return retries >= cap

	def _signal_samantha_worker(self):
		"""NON-BLOCKING: check if there are pending Samantha tasks and signal the worker thread."""
		if not self._samantha_worker:
			return
		try:
			from red_pill.cognitive.queue_manager import CognitiveQueueManager
			from red_pill.inference.samantha_worker import SAMANTHA_SOURCE

			qm = CognitiveQueueManager()
			if qm.has_pending(source=SAMANTHA_SOURCE):
				self._samantha_worker.wake()
		except Exception as e:
			logger.error(f"[IDEWorker] Samantha signal failed: {e}")

	def _watchdog_samantha(self):
		"""Monitor SamanthaWorker thread health. Restart if stuck or dead."""
		if not self._samantha_worker:
			return
		try:
			if not self._samantha_worker.is_alive():
				logger.error("[Watchdog] SamanthaWorker thread died — restarting")
				self._restart_samantha_worker()
			elif not self._samantha_worker.is_healthy():
				logger.error(f"[Watchdog] SamanthaWorker hung (task: {self._samantha_worker._current_task_id}) — killing")
				# Kill ephemeral process if running
				self._samantha_worker.force_kill_ephemeral()
				# Mark current task as frustrated
				if self._samantha_worker._current_task_id:
					try:
						from red_pill.cognitive.queue_manager import CognitiveQueueManager

						qm = CognitiveQueueManager()
						qm.mark_failed(self._samantha_worker._current_task_id, "Watchdog timeout")
					except Exception:
						pass
				# Restart the thread
				self._restart_samantha_worker()
		except Exception as e:
			logger.error(f"[Watchdog] Samantha check failed: {e}")

	def _restart_samantha_worker(self):
		"""Restart the SamanthaWorker thread."""
		try:
			if self._samantha_worker:
				self._samantha_worker.stop()
			from red_pill.inference.samantha_worker import SamanthaWorker

			self._samantha_worker = SamanthaWorker()
			self._samantha_worker.start()
			logger.info("[Watchdog] SamanthaWorker restarted")
		except Exception as e:
			logger.error(f"[Watchdog] SamanthaWorker restart failed: {e}")
			self._samantha_worker = None

	def process_inbox(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		debounce_seconds = cfg.REACTIVE_DEBOUNCE_SECONDS if cfg.REACTIVE_DEBOUNCE_ENABLED else 0

		cursor.execute(
			"""
			SELECT channel_user_id
			FROM inbox
			WHERE status = 'PENDING'
			GROUP BY channel_user_id
			HAVING (strftime('%s', 'now') - strftime('%s', max(created_at))) >= ?
				OR sum(case when payload LIKE '%"command"%' then 1 else 0 end) > 0
			LIMIT 1
			""",
			(debounce_seconds,),
		)
		user_row = cursor.fetchone()

		if not user_row:
			conn.close()
			return

		channel_user_id = user_row["channel_user_id"]
		cursor.execute("SELECT * FROM inbox WHERE status = 'PENDING' AND channel_user_id = ? ORDER BY created_at ASC", (channel_user_id,))
		rows = cursor.fetchall()

		conversational_msgs = []
		background_msgs = []
		parsed_msgs = {}
		for r in rows:
			msg = parse_payload(r["channel"], r["channel_user_id"], r["payload"])
			parsed_msgs[r["id"]] = msg
			if msg.mode == "background":
				background_msgs.append(r)
			else:
				conversational_msgs.append(r)

		# Handle Background Messages
		if background_msgs:
			from red_pill.core.inbox import MinionInbox

			inbox = MinionInbox()
			for r in background_msgs:
				msg_id = r["id"]
				try:
					msg = parsed_msgs.get(msg_id)  # type: ignore[assignment]
					text = msg.text if msg else ""
					sender_id = (msg.sender_id if msg else None) or r["channel_user_id"]
					channel = r["channel"]

					inbox.drop_report(
						event_id=f"bg_msg_{msg_id}", source=f"NeonLink ({channel})", status="pending", content=f"Message from {sender_id}: {text}"
					)
					cursor.execute("UPDATE inbox SET status = 'DELIVERED_BACKGROUND' WHERE id = ?", (msg_id,))
				except Exception as e:
					logger.error(f"Failed background delivery for msg {msg_id}: {e}")
					cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (msg_id,))
			conn.commit()

		if not conversational_msgs:
			conn.close()
			return

		# Handle Conversational Messages (Compaction)
		first_conv = conversational_msgs[0]
		first_msg = parsed_msgs.get(first_conv["id"]) or parse_payload(first_conv["channel"], first_conv["channel_user_id"], first_conv["payload"])
		first_payload = first_msg.payload
		command = first_msg.command

		logger.debug(f"[Worker] command={command}, channel={first_msg.channel}, payload={first_payload}")

		channel = first_conv["channel"]

		if command == "LIST_CASCADES":
			from red_pill.telegram.session import TelegramSessionManager

			tsm = TelegramSessionManager()
			sessions = tsm.list_sessions(channel_user_id)

			cursor.execute("DELETE FROM cascade_mappings WHERE channel_user_id = ?", (channel_user_id,))
			response_text = "🧠 **Sesiones de Telegram Activas:**\n\n"
			if not sessions:
				response_text += "_No hay sesiones activas. Envía un mensaje o /new para crear una._\n"
			else:
				for i, sess in enumerate(sessions[:5]):
					idx = i + 1
					cid = sess["id"]
					title = sess.get("summary", {}).get("summary", "Sin Título")
					cursor.execute(
						"INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES (?, ?, ?)", (channel_user_id, cid, title)
					)
					response_text += f"`[{idx}]` {title}\n"
			response_text += "\nEnvía `/switch <número>` para anclar tu sesión."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": response_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SWITCH_CASCADE":
			idx = first_payload.get("index")  # type: ignore[assignment]
			cursor.execute(
				"SELECT cascade_id, title FROM cascade_mappings WHERE channel_user_id = ? AND id = (SELECT id FROM cascade_mappings WHERE channel_user_id = ? ORDER BY id ASC LIMIT 1 OFFSET ?)",
				(channel_user_id, channel_user_id, idx - 1),
			)
			mapping = cursor.fetchone()
			if mapping:
				cid = mapping["cascade_id"]
				title = mapping["title"]
				cursor.execute(
					"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
					(channel_user_id, cid),
				)
				resp_text = f"🔗 Sesión anclada a: **{title}**.\nTodos los mensajes se inyectarán en esta conversación."
			else:
				resp_text = "❌ Índice no encontrado. Usa `/list` primero."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "NEW_CASCADE":
			from red_pill.telegram.session import TelegramSessionManager

			tsm = TelegramSessionManager()
			new_session = tsm.create_session(channel_user_id)
			new_id = new_session["id"]

			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type, model, backend) VALUES (?, ?, 'local_session', NULL, NULL)",
				(channel_user_id, new_id),
			)
			resp_text = "✨ Nueva sesión de Telegram inicializada y anclada correctamente.\nEl contexto está a cero. ¿En qué puedo ayudarte?"
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "LIST_MODELS":
			# /models [--backend X] — lista el catálogo curado (D6/D7), sin agente.
			from red_pill.core.model_catalog import ModelCatalog

			try:
				catalog = ModelCatalog()
				models = catalog.models(backend=first_payload.get("backend"))
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Model catalog error: {e}")
				resp_text = f"⚠️ No se pudo leer el catálogo de modelos: {e}"
			else:
				if not models:
					resp_text = "ℹ️ No hay modelos curados."
				else:
					lines = []
					for m in models:
						roles = ", ".join(m.get("roles", []) or []) or "-"
						lines.append(f"• `{m['id']}` — {m.get('tier')} (prio {m.get('priority')}) roles: {roles}")
					resp_text = "🧠 **Modelos curados:**\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SET_MODEL":
			# /model <id> — valida contra el catálogo (D7) y persiste backend del catálogo (D8).
			from red_pill.core.model_catalog import ModelCatalog

			model_id = first_payload.get("model", "").strip()
			try:
				catalog = ModelCatalog()
				entry = catalog.get(model_id)
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Model catalog error: {e}")
				entry = None
			if not entry:
				resp_text = f"❌ El modelo `{model_id}` no está en el catálogo curado. Usa `/models` para ver los disponibles."
			else:
				backend = entry.get("backend")
				cursor.execute(
					"UPDATE telegram_sessions SET model = ?, backend = ? WHERE channel_user_id = ?",
					(model_id, backend, channel_user_id),
				)
				resp_text = f"✅ Modelo de sesión establecido: `{model_id}` (backend `{backend}`)."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SHOW_MODEL":
			cursor.execute("SELECT model, backend FROM telegram_sessions WHERE channel_user_id = ?", (channel_user_id,))
			row = cursor.fetchone()
			if row and row["model"]:
				resp_text = f"🔧 Modelo de sesión actual: `{row['model']}` (backend `{row['backend']}`)."
			else:
				resp_text = "ℹ️ Sin override de modelo — la sesión usa la cascade configurada en `.env`."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "RESET_MODEL":
			cursor.execute("UPDATE telegram_sessions SET model = NULL, backend = NULL WHERE channel_user_id = ?", (channel_user_id,))
			resp_text = "↩️ Override de modelo eliminado — se vuelve a la cascade configurada en `.env`."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SHOW_QUEUE":
			# /queue — estado de la cola central (script tonto, sin agente).
			from red_pill.cognitive.queue_manager import CognitiveQueueManager

			try:
				queue = CognitiveQueueManager()
				tasks = queue.list_tasks(limit=10)
			except Exception as e:
				logger.error(f"[{first_conv['id']}] Queue read error: {e}")
				resp_text = f"⚠️ No se pudo leer la cola: {e}"
			else:
				if not tasks:
					resp_text = "🗂️ La cola de jobs está vacía."
				else:
					lines = []
					for t in tasks:
						title = (t.get("title") or "")[:40]
						lines.append(f"• `{t['id'][:8]}` **{t['status']}** prio={t['priority']} {title}")
					resp_text = "🗂️ **Cola de jobs activos:**\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "LIST_DEFERRED":
			# /deferred — lista mensajes DEFERRED (D13, quota agotada).
			cursor.execute("SELECT id, payload, retries FROM inbox WHERE status = 'DEFERRED' AND channel_user_id = ?", (channel_user_id,))
			rows = cursor.fetchall()
			if not rows:
				resp_text = "ℹ️ No hay mensajes DEFERRED para esta sesión."
			else:
				lines = []
				for r in rows:
					text = ""
					try:
						text = (json.loads(r["payload"]).get("text") or "")[:50]
					except Exception:
						pass
					lines.append(f"• `{r['id']}` (intentos {r['retries']}): {text}")
				resp_text = "📋 **Mensajes DEFERRED** (quota agotada — usa `/model` con un modelo con quota o espera):\n" + "\n".join(lines)
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "HEAVY_PATH":
			# /mission <prompt> — fuerza el heavy path (Fase 2): encola agentic_job.
			# Implementación completa en la Fase 2; aquí delega en _enqueue_heavy.
			self._enqueue_heavy_path(
				text=first_payload.get("text", ""),
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=[first_conv["id"]],
				cursor=cursor,
				conn=conn,
			)
			return

		# Build compacted prompt
		buffer_texts = []
		msg_ids_to_process = []
		for cr in conversational_msgs:
			try:
				p = json.loads(cr["payload"])
				text = p.get("text", "")
				buffer_texts.append(text)
				msg_ids_to_process.append(cr["id"])
			except Exception:
				pass

		if not msg_ids_to_process:
			conn.close()
			return

		combined_text = "\n".join(buffer_texts)

		# Handle Delete Command
		combined_text_clean = combined_text.strip()
		if combined_text_clean.startswith("/delete"):
			parts = combined_text_clean.split()
			target_id = None
			title = ""

			from red_pill.telegram.session import TelegramSessionManager

			tsm = TelegramSessionManager()

			if len(parts) == 2 and parts[1].isdigit():
				idx = int(parts[1])
				cursor.execute(
					"SELECT cascade_id, title FROM cascade_mappings WHERE channel_user_id = ? AND id = (SELECT id FROM cascade_mappings WHERE channel_user_id = ? ORDER BY id ASC LIMIT 1 OFFSET ?)",
					(channel_user_id, channel_user_id, idx - 1),
				)
				mapping = cursor.fetchone()
				if mapping:
					target_id = mapping["cascade_id"]
					title = mapping["title"]
				else:
					resp_text = "❌ Índice no encontrado. Usa `/list` primero."
			else:
				# Delete currently active session
				cursor.execute(
					"SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
					(channel_user_id,),
				)
				session_row = cursor.fetchone()
				if session_row:
					target_id = session_row["cascade_id"]
					sess = tsm.get_session(target_id)  # type: ignore[assignment]
					if sess:
						title = sess.get("summary", {}).get("summary", "Sin Título")
				else:
					resp_text = "❌ No tienes ninguna sesión activa para eliminar."

			if target_id:
				success = tsm.mark_for_deletion(target_id)
				if success:
					cursor.execute(
						"DELETE FROM telegram_sessions WHERE channel_user_id = ? AND cascade_id = ?",
						(channel_user_id, target_id),
					)
					resp_text = f"🗑️ La sesión **{title}** ha sido marcada para eliminación y copiada a la cola de ingesta. Se purgará del disco una vez archivada."
				else:
					resp_text = "❌ Error al intentar eliminar la sesión."

			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		# ---- System channel: AWAKENINGs run in isolation (no Telegram session) ----
		# A configured AWAKENING cascade forces the bridge path even when
		# capabilities degraded (bridge construction failed) — never fall through
		# to a backend's legacy polling path on behalf of other backends.
		if channel == "system" and ((self._caps and self._caps.auto_approve) or cfg.get_config().AWAKENING_BRIDGE_CASCADE):
			self._process_awakening(combined_text, msg_ids_to_process, cursor, conn, channel_user_id=channel_user_id)
			conn.commit()
			conn.close()
			return

		# ---- Touch idle-detection file for non-AWAKENING messages ----
		# This prevents autonomous_cron from thinking the operator is idle
		# when they are actively chatting via Telegram.
		try:
			activity_file = get_state_dir() / "last_user_activity.txt"
			activity_file.parent.mkdir(parents=True, exist_ok=True)
			activity_file.touch()
		except Exception:
			pass

		# ---- AgentBridge: Direct execution path (bridge cascade) ----
		# Telegram is served by the configured bridge cascade (opencode, AD-034):
		# the legacy interactive-cascade fusion is gone.
		if (self._caps and self._caps.auto_approve) or cfg.get_config().TELEGRAM_BRIDGE_CASCADE:
			self._process_via_bridge(combined_text, msg_ids_to_process, channel, channel_user_id, cursor, conn)
			conn.commit()
			conn.close()
			return

		# No bridge configured: Telegram is served through the bridge (AD-034). The
		# legacy interactive-cascade fusion (cascade binding) was removed.
		logger.error(f"[{msg_ids_to_process}] No TELEGRAM_BRIDGE_CASCADE configured — cannot process Telegram message.")
		for m_id in msg_ids_to_process:
			cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (m_id,))
		conn.commit()
		conn.close()

	def _process_via_bridge(self, combined_text, msg_ids, channel, channel_user_id, cursor, conn):
		"""External Scribe Pattern: direct prompt → response → scribe → outbox.

		Uses the configured bridge for synchronous, auto-approved prompt
		execution. Uses TelegramSessionManager for local context preservation.
		"""
		import re

		from red_pill.telegram.session import TelegramSessionManager

		backend_label = self._caps.backend.value.upper() if self._caps else "UNBUILT"
		logger.info(f"[{msg_ids}] Processing via {backend_label} bridge (Local Session Context)")

		# D2/D10 (Fase 1, signal-only): detect an explicit routing keyword at the
		# start of the message. We strip it from the PROMPT (it is routing, not
		# content) but keep the ORIGINAL text for the session history (D11, so
		# telegram_session dedup keeps matching). Fase 1 executes as fast path;
		# the keyword is logged for forward-compatibility with Fase 2.
		routing_keyword = _detect_routing_keyword(combined_text)
		prompt_text = combined_text
		if routing_keyword:
			# Fase 2: el keyword dispara el heavy path (encola agentic_job). El
			# prompt sin keyword (D10) se encola; el historial conserva el original (D11).
			logger.info(f"[{msg_ids}] Routing keyword detected: {routing_keyword} → heavy path")
			self._enqueue_heavy_path(
				text=combined_text.strip()[len(routing_keyword) :].lstrip(),
				history_text=combined_text,
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=msg_ids,
				cursor=cursor,
				conn=conn,
			)
			return

		tsm = TelegramSessionManager()

		# Get active local session ID
		cursor.execute(
			"SELECT cascade_id, model, backend FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
			(channel_user_id,),
		)
		session_row = cursor.fetchone()

		# D9 (override de sesión): si el operador fijó un modelo con /model, la
		# cascade dinámica antepone ese modelo a la cascade configurada, sin
		# duplicar si ya coincide con algún target (resuelto por ModelCatalog).
		session_model = session_row["model"] if session_row else None
		session_backend = session_row["backend"] if session_row else None
		bridge_telegram = self._bridge_telegram
		if session_model:
			try:
				from red_pill.core.model_catalog import ModelCatalog

				catalog = ModelCatalog()
				cascade_targets = catalog.cascade_for(model_id=session_model)
				if cascade_targets:
					from red_pill.config import BridgeTarget
					from red_pill.swarm.bridges.factory import create_cascade_bridge

					targets = [BridgeTarget(**t) for t in cascade_targets]
					override_bridge = create_cascade_bridge(targets, name="TELEGRAM_SESSION_OVERRIDE")
					if override_bridge:
						logger.info(f"[{msg_ids}] Session model override: {session_model} (backend={session_backend})")
						bridge_telegram = override_bridge
			except Exception as e:
				logger.warning(f"[{msg_ids}] Session model override failed, using default cascade: {e}")

		if session_row:
			session_id = session_row["cascade_id"]
			session = tsm.get_session(session_id)
			if not session or session.get("status") == "pending_purge":
				session = tsm.create_session(channel_user_id)
				session_id = session["id"]
				cursor.execute(
					"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
					(channel_user_id, session_id),
				)
		else:
			session = tsm.create_session(channel_user_id)
			session_id = session["id"]
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
				(channel_user_id, session_id),
			)

		# 1. Append User Message
		tsm.append_message(session_id, "user", combined_text)

		# 2. Build Consolidated prompt — separate history from current message
		# Get history WITHOUT the just-appended message (it goes in a separate block)
		session = tsm.get_session(session_id)
		all_steps = session.get("steps", []) if session else []
		history_steps = all_steps[:-1] if all_steps else []

		# Truncation fallback: if compaction is pending but not done,
		# keep only the last 12 steps to prevent unbounded token growth.
		TRUNCATION_THRESHOLD = 20  # Slightly above compaction threshold (16)
		TRUNCATION_KEEP = 12
		if len(history_steps) > TRUNCATION_THRESHOLD:
			truncated_count = len(history_steps) - TRUNCATION_KEEP
			history_steps = history_steps[-TRUNCATION_KEEP:]
			logger.info(f"[Telegram] Truncated history: dropped {truncated_count} steps (compaction pending)")
			history_lines = [f"[Contexto anterior truncado: {truncated_count} mensajes omitidos. Compactación pendiente vía Samantha.]"]
		else:
			history_lines = []

		for step in history_steps:
			role = step.get("intent", "USER")
			txt = step.get("message", {}).get("text", "")
			if txt:
				history_lines.append(f"{role}: {txt}")
		history_text = "\n\n".join(history_lines)

		prompt = (
			f"<user_rules>\n"
			f"<RULE[user_global]>\n"
			f'<constraint critical="true" level="0" name="telegram_session">\n'
			f"CRITICAL: Respond ONLY to the <current_message> below. The history is for context only.\n"
			f"MANDATORY FIRST STEPS:\n"
			f"1. {_handshake_step('<the current_message text>', cfg.get_config().IDENTITY_DEPTH_NEON_LINK)}\n"
			f"2. Then respond to the user's message.\n"
			f"</constraint>\n"
			f"</RULE[user_global]>\n"
			f"</user_rules>\n\n"
		)

		if history_text:
			prompt += f"<conversation_history>\n{history_text}\n</conversation_history>\n\n"

		prompt += f"<current_message>\n{prompt_text}\n</current_message>\n"

		if not bridge_telegram:
			logger.error(f"[{msg_ids}] No bridge available to execute prompt")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, error_text="no bridge available")
			return

		# D23: commit-pre-prompt — release the events.db write-lock BEFORE the
		# (potentially 300s) bridge call. The session INSERT OR REPLACE and
		# user-message append are already consistent here. Without this, the
		# implicit transaction keeps the write-lock for the whole prompt, which
		# blocks neon-link's ingest/drain (BEGIN IMMEDIATE + busy_timeout=5000 →
		# abort at ~5s) and would block the D21 heartbeat thread's UPDATE.
		conn.commit()
		# D21: keep the heartbeat lease fresh before the blocking bridge call.
		self._touch_lease()

		try:
			result = bridge_telegram.prompt(prompt, timeout=cfg.get_config().TELEGRAM_INLINE_TIMEOUT)
		except (NoModelsConfigured, AllModelsExhausted) as e:
			# D13: cascade exhausta (vacía, o sin modelo con quota) → el mensaje NO
			# se marca PROCESSED (nunca se reintentaría). Se marca DEFERRED:
			# retry-able vía /deferred cuando vuelva quota/recursos. Sin reintento
			# automático y sin detector de quota (fuera de alcance).
			logger.error(f"[{msg_ids}] Cascade exhausted: {e}")
			# D20 (Fase 3): consciencia de quota — marcar los targets sin quota
			# para saltarlos en el siguiente intento.
			try:
				from red_pill.core.model_router import get_router

				for t, _err in getattr(e, "errors", []) or []:
					label = getattr(t, "model", None) or f"{t.backend}/default"
					get_router().mark_exhausted(label)
			except Exception:
				pass
			err_text = _format_cascade_error(e)
			if channel != "system":
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(
						channel,
						channel_user_id,
						None,
						json.dumps({"text": err_text + "\n\n_El mensaje queda DEFERRED — cuando creas que ha vuelto la quota, usa /deferred._"}),
					),
				)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEFERRED' WHERE id = ?", (m_id,))
			return
		except Exception as e:
			logger.error(f"[{msg_ids}] Bridge execution failed: {e}")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, exc=e)
			return

		if not result.ok:
			logger.error(f"[{msg_ids}] Bridge returned error: {result.error}")
			self._handle_retry_failure(msg_ids, channel, channel_user_id, cursor, error_text=result.error or "unknown error")
			return

		response = result.response

		# D14 (Fase 2): si el modelo emite [ESCALATE], la tarea se ENCOLA como
		# heavy path y el usuario recibe "⏳ en cola". La respuesta del fast path
		# no se entrega (el modelo solo señaló la intención); se encola la
		# petición original (prompt_text) con el contexto de sesión.
		if _detect_escalate_marker(response):
			model_label = getattr(result, "model", None) or "unknown"
			logger.info(f"[{msg_ids}] [ESCALATE] marker detected (model={model_label}) → heavy path enqueue")
			tsm.append_message(session_id, "assistant", response)
			self._enqueue_heavy_path(
				text=prompt_text,
				channel=channel,
				channel_user_id=channel_user_id,
				msg_ids=msg_ids,
				cursor=cursor,
				conn=conn,
			)
			return

		# 3. Append Assistant Response to session history
		tsm.append_message(session_id, "assistant", response)

		# External Scribe
		try:
			self._scribe_relay(user_prompt=combined_text, agent_response=response, model=result.model, session_id=session_id)
		except Exception as e:
			logger.warning(f"[{msg_ids}] Scribe relay failed (non-fatal): {e}")

		# Tag processing pipeline
		log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", response, re.DOTALL)
		for log_msg in log_matches:
			try:
				from red_pill.core.paths import get_latest_awakening_log

				log_path = get_latest_awakening_log()
				if log_path.exists():
					import datetime

					timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
					with open(log_path, "a") as f:
						f.write(f"\n- **[{timestamp}]** (Telegram): {log_msg.strip()}")
			except Exception as e:
				logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

		# Strip tags for clean outbox output
		clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", response, flags=re.DOTALL).strip()

		if not clean_content:
			clean_content = "⚠️ El agente procesó tu mensaje pero no generó respuesta. Reintenta en unos segundos."

		# Evitar enviar respuestas de Derecho al Silencio a Telegram
		if channel != "system" and not is_silence_response(clean_content):
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": clean_content})),
			)

		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))

		# 4. Trigger compaction check
		new_session_id = tsm.trigger_compaction(session_id, self._bridge_telegram)
		if new_session_id:
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'local_session')",
				(channel_user_id, new_session_id),
			)

		logger.info(f"[{msg_ids}] Processed via bridge. Response length: {len(clean_content)} chars")

	def _process_awakening(self, combined_text, msg_ids, cursor, conn, channel_user_id: str = "system"):
		"""Process AWAKENING messages in isolation — no Telegram session history.

		Each AWAKENING gets a fresh bridge conversation. Output is still
		routed to the Telegram outbox so the user sees the result, but
		the conversation history is never mixed with user sessions.

		A failed attempt counts against the daily cap (it consumed resources)
		and is retried with the same D24 policy as Telegram messages: a timeout
		gets one retry, a transient error up to three attempts; then the message
		goes DEAD (+ dead_letters) so an outage cannot burn the whole day's cap.
		"""
		import re

		logger.info(f"[{msg_ids}] Processing AWAKENING in isolated context")

		# ── Budget Guard: check daily AWAKENING limit (día local) ──
		# `started_at` es UTC (CURRENT_TIMESTAMP); se compara en hora local
		# ('localtime') para alinear el reinicio del tope con el operador.
		# Solo cuentan los despertares productivos (`counted=1`): los que
		# ejercen el Derecho al Silencio quedan a 0 salvo política
		# AWAKENING_SILENCE_COUNTS (AWAKEN-002).
		# Recuento + INSERT atómicos entre procesos: BEGIN IMMEDIATE toma el lock
		# de escritura ANTES de contar, así dos workers no leen ambos 7/8 y pasan
		# los dos. Si la conexión ya está en una transacción, ya escribió y tiene
		# el lock. Se libera en el commit previo a la llamada al puente (D23).
		if not conn.in_transaction:
			conn.execute("BEGIN IMMEDIATE")
		today_count = cursor.execute(
			"SELECT COUNT(*) FROM execution_ledger WHERE exec_type = 'awakening' "
			"AND date(started_at, 'localtime') = date('now', 'localtime') AND counted = 1"
		).fetchone()[0]

		if today_count >= MAX_AWAKENINGS_PER_DAY:
			logger.warning(f"[{msg_ids}] AWAKENING budget exhausted: {today_count}/{MAX_AWAKENINGS_PER_DAY} today. Discarding.")
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
			return

		logger.info(f"[{msg_ids}] AWAKENING budget: {today_count + 1}/{MAX_AWAKENINGS_PER_DAY}")

		# ── Register in ledger (status=started) ──
		cursor.execute("INSERT INTO execution_ledger (exec_type, status) VALUES ('awakening', 'started')")
		ledger_id = cursor.lastrowid
		start_time = time.time()

		# ── Build prompt: agent loads identity via the kernel handshake (mode=headless) ──
		# Provider-agnostic: no client-specific tool names; each bridge adapts the
		# RedPill-Kernel tool names to its own client.
		prompt = (
			f"<user_rules>\n"
			f"<RULE[user_global]>\n"
			f'<constraint critical="true" level="0" name="headless_awakening">\n'
			f"CRITICAL: You are running HEADLESS in an autonomous background session — nobody is there to approve anything.\n"
			f"BUDGET: You have a HARD LIMIT of {AWAKENING_MAX_TOOL_CALLS} tool calls for this session. "
			f"Plan your work efficiently. If the task requires more, stop and leave a summary for the next awakening.\n"
			f"TOOLS: NEVER use a tool or command that waits for user approval or input (it hangs until the timeout). "
			f"PERMITTED: file read/edit tools, the RedPill-Kernel MCP tools, and non-interactive shell commands "
			f"scoped to your worktree (including the `git worktree add` that creates it) or to the desk "
			f"(${{AGENT_CORE_DIR}}).\n"
			f"WORKTREE RULE (HARD): any work that writes to a PROJECT/kernel repo is created and done in a "
			f"`git worktree` on its own branch (`awaken/<ts>` or the designated feature branch) — NEVER in the live "
			f"tree, never change the live branch's HEAD. The DESK (${{AGENT_CORE_DIR}}) is exempt (commit to `main`+push allowed).\n"
			f"TESTS: run them from the worktree root (pytest imports that worktree's own `src`); a green run in the "
			f"live checkout does not validate your branch.\n"
			f"RESUME-FIRST: at the start, before new work, read the last awakening logs "
			f"(`${{AGENT_CORE_DIR}}/awakening/`) and any RFC/note they point to; if a previous awakening left work "
			f"in progress (worktree/branch/commit), RESUME it there instead of starting fresh.\n"
			f"RECORD-WHERE-YOU-WORKED (HARD): every time you start or resume work in a worktree, write in your "
			f"awakening log AND in the RFC/note owning that work: the branch, the worktree path, and the last commit. "
			f"This is the handoff — without it the next awakening cannot find the work.\n"
			f"WORK OVERLAP GUARD: BEFORE submitting any `job_manager_api job_submit` (especially a dag_job), "
			f"call `job_manager_api job_list` and check for any in-flight DAG job (source=dag_job, status PENDING/PROCESSING/RESUMING). "
			f"If one is running, DO NOT launch a new DAG job — dedicate this awakening to monitoring that DAG (job_status) "
			f"and scanning for other issues (`metabolism_health_api fetch_signal_memories`, "
			f"`swarm_orchestrator_api check_minion_inbox`, `metabolism_health_api check_system_health`). "
			f"If `fetch_signal_memories` shows an active `memory_bank_bloat_<ws>` pain signal, read that workspace's "
			f"`bank_health.json` (via `bunker_memory_api read_workspace_memory`) and include a one-line summary "
			f"(biggest file, orphans, broken refs) in your report, offering the operator on-demand semantic compaction — "
			f"NEVER auto-compact (operator decision 2026-09-03).\n"
			f'If you DO launch a DAG while none is in flight, include `"origin": "awakening"` in its payload so its '
			f"minion sessions are not mistaken for operator activity by the next awakening.\n"
			f"MANDATORY FIRST STEPS:\n"
			f"1. {_handshake_step('<your awakening directive>', cfg.get_config().IDENTITY_DEPTH_HEADLESS)}\n"
			f"2. RESUME CHECK: read the last awakening logs `${{AGENT_CORE_DIR}}/awakening/` and any RFC/note they "
			f"point to; if a prior awakening left work in a worktree (branch + path + commit), note it and resume "
			f"THERE before starting anything new.\n"
			f"3. Hydrate the workspace bank (max 2 calls, skip if CWD is outside every registered workspace): "
			f"call `bunker_memory_api read_workspace_memory` for `MEMORY.md` of the workspace owning your CWD, "
			f"plus its `bank_health.json`; if `thresholds_tripped` is non-empty, include it in your report — "
			f"semantic compaction is operator on-demand, never auto-compact.\n"
			f"4. Then proceed with your autonomous work.\n"
			f"{_awakening_planner_directive(cfg.get_config().AWAKENING_PLANNER_ACCESS)}\n"
			f"{_awakening_channel_directive()}\n"
			f"</constraint>\n"
			f"</RULE[user_global]>\n"
			f"</user_rules>\n\n"
			f"{combined_text}\n"
		)

		if not self._bridge_awakening:
			logger.error(f"[{msg_ids}] No bridge available for AWAKENING")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = 0 WHERE id = ?",
				(ledger_id,),
			)
			self._handle_retry_failure(msg_ids, "system", channel_user_id, cursor, error_text="no bridge available")
			return

		# D23: commit-pre-prompt — release the events.db write-lock (execution_ledger
		# INSERT above) before the long AWAKENING bridge call.
		conn.commit()
		# D21: keep the heartbeat lease fresh before the blocking bridge call.
		self._touch_lease()

		try:
			with self._lease_keeper():
				result = self._bridge_awakening.prompt(prompt, timeout=cfg.get_config().AWAKENING_TIMEOUT)
		except Exception as e:
			duration = time.time() - start_time
			logger.error(f"[{msg_ids}] AWAKENING execution failed after {duration:.0f}s: {e}")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = ? WHERE id = ?",
				(duration, ledger_id),
			)
			self._handle_retry_failure(msg_ids, "system", channel_user_id, cursor, exc=e)
			return

		duration = time.time() - start_time

		if not result.ok:
			logger.error(f"[{msg_ids}] AWAKENING returned error after {duration:.0f}s: {result.error}")
			cursor.execute(
				"UPDATE execution_ledger SET status = 'error', duration_s = ? WHERE id = ?",
				(duration, ledger_id),
			)
			self._handle_retry_failure(msg_ids, "system", channel_user_id, cursor, error_text=result.error or "unknown error")
			return

		response = result.response

		# ── Update ledger with success ──
		cursor.execute(
			"UPDATE execution_ledger SET status = 'completed', duration_s = ?, response_len = ?, conversation_id = ? WHERE id = ?",
			(duration, len(response), result.conversation_id or "", ledger_id),
		)
		logger.info(f"[{msg_ids}] AWAKENING completed in {duration:.0f}s ({len(response)} chars)")

		# SOVEREIGN_LOG tag processing (same as _process_via_bridge)
		log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", response, re.DOTALL)
		for log_msg in log_matches:
			try:
				from red_pill.core.paths import get_latest_awakening_log

				log_path = get_latest_awakening_log()
				if log_path.exists():
					import datetime

					timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
					with open(log_path, "a") as f:
						f.write(f"\n- **[{timestamp}]** (Awakening): {log_msg.strip()}")
			except Exception as e:
				logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

		# Strip tags for clean output
		clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", response, flags=re.DOTALL).strip()

		# Derecho al Silencio: don't send to Telegram
		is_silence = is_silence_response(clean_content)

		# El silencio no consume el tope diario salvo política explícita. Los
		# errores sí cuentan (consumieron recursos) — el INSERT ya dejó counted=1.
		if is_silence and not cfg.get_config().AWAKENING_SILENCE_COUNTS:
			cursor.execute("UPDATE execution_ledger SET counted = 0 WHERE id = ?", (ledger_id,))
			logger.info(f"[{msg_ids}] AWAKENING silence — no consume tope (counted=0)")

		if clean_content and not is_silence:
			# Route to Telegram outbox — find the user's telegram channel_user_id
			tg_row = cursor.execute("SELECT channel_user_id FROM telegram_sessions WHERE cascade_type = 'local_session' LIMIT 1").fetchone()
			if tg_row:
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					("telegram", tg_row["channel_user_id"], None, json.dumps({"text": clean_content})),
				)
				logger.info(f"[{msg_ids}] AWAKENING output routed to Telegram outbox ({len(clean_content)} chars)")
			else:
				logger.warning(f"[{msg_ids}] AWAKENING produced output but no Telegram session found to deliver")
		elif is_silence:
			logger.info(f"[{msg_ids}] AWAKENING: Derecho al Silencio exercised (not sent to Telegram)")

		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))

	def _scribe_relay(self, user_prompt: str, agent_response: str, model: Optional[str] = None, session_id: Optional[str] = None):
		"""External Scribe: queue prompt+response for ingestion.

		Telegram has no editor hook, so this worker is the capture surface for its
		headless turns: it queues into the same `memory_queue` every other surface
		uses, carrying the Telegram session uuid so the purge gate and the
		`telegram:<uuid>` chronicle source agree.
		"""
		try:
			from red_pill.core.queue_manager import MemoryQueueManager

			MemoryQueueManager().enqueue_memory(
				prompt=user_prompt,
				response=agent_response,
				role="assistant",
				originator="telegram",
				model=model,
				session_id=session_id,
			)
			logger.debug("[Scribe] Turn queued for ingestion (originator=telegram)")
		except Exception as e:
			# Non-fatal: log but don't block the pipeline
			logger.warning(f"[Scribe] Failed to queue interaction: {e}")

	def _session_cascade_specs(self, channel_user_id: str, cursor) -> List[Dict[str, Any]]:
		"""Cascade de BridgeTarget (dicts) para el heavy path (D16).

		Si la sesión tiene override de modelo (/model), usa la cascade del
		catálogo anteponiendo ese modelo (D9). Si no, usa la cascade configurada
		en .env (TELEGRAM_BRIDGE_CASCADE). El payload del agentic_job lleva
		`cascade` — el driver construye CascadeBridge con esos targets (D16:
		siempre cascade, nunca backend/model/effort sueltos).
		"""

		cfg_inst = cfg.get_config()
		# Override de sesión — router con consciencia de quota (D9/D20).
		cursor.execute("SELECT model FROM telegram_sessions WHERE channel_user_id = ?", (channel_user_id,))
		row = cursor.fetchone()
		session_model = row["model"] if row and row["model"] else None
		if session_model:
			try:
				from red_pill.core.model_router import get_router

				entries = get_router().resolve_cascade(role="conversational", session_model=session_model)
				if entries:
					return [{"backend": e["backend"], "model": e["id"], "timeout": e.get("timeout")} for e in entries]
			except Exception as e:
				logger.warning(f"[HeavyPath] router cascade failed, using .env cascade: {e}")
		# Cascade configurada (.env)
		specs: List[Dict[str, Any]] = []
		for t in cfg_inst.TELEGRAM_BRIDGE_CASCADE:
			entry: Dict[str, Any] = {"backend": t.backend, "model": t.model}
			if t.timeout:
				entry["timeout"] = t.timeout
			if t.effort:
				entry["effort"] = t.effort
			specs.append(entry)
		return specs

	def _enqueue_heavy_path(self, text: str, channel: str, channel_user_id: str, msg_ids, cursor, conn, history_text: Optional[str] = None) -> None:
		"""Fase 2: encola un agentic_job con cascade de sesión (D16/D17/D18) y
		acusa "⏳ en cola". El resultado lo entrega _check_telegram_jobs() (D19).

		`text` es el prompt de la tarea (ya sin keyword, D10). `history_text`
		(opcional) es la versión ORIGINAL del mensaje para el historial (D11) —
		si no se pasa, se usa `text`.

		Usa el contexto de la sesión (historial) como prompt. mission_id con
		prefijo `telegram:` (D18) + payload.telegram_channel_user_id para el
		delivery por Telegram.
		"""
		from red_pill.cognitive.queue_manager import CognitiveQueueManager
		from red_pill.telegram.session import TelegramSessionManager

		if not text:
			logger.error(f"[{msg_ids}] HEAVY_PATH sin texto — ignorando")
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		# Construir prompt con contexto de sesión (historial local)
		tsm = TelegramSessionManager()
		cursor.execute(
			"SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'local_session'",
			(channel_user_id,),
		)
		row = cursor.fetchone()
		session_id = row["cascade_id"] if row else None
		if not session_id:
			# Crear sesión si el operador encoló antes de chatear (D11: contexto).
			session = tsm.create_session(channel_user_id)
			session_id = session["id"]
			cursor.execute(
				"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type, model, backend) VALUES (?, ?, 'local_session', NULL, NULL)",
				(channel_user_id, session_id),
			)
		prompt = text
		if session_id:
			session = tsm.get_session(session_id)  # type: ignore[assignment]
			if session:
				steps = session.get("steps", [])
				history = "\n".join(
					f"{s.get('intent', 'USER')}: {s.get('message', {}).get('text', '')}" for s in steps if s.get("message", {}).get("text")
				)
				if history:
					prompt = f"<conversation_history>\n{history[-4000:]}\n</conversation_history>\n\n<current_task>\n{text}\n</current_task>"
		# Append user message to session history (D11: versión ORIGINAL con keyword)
		if session_id:
			tsm.append_message(session_id, "user", history_text or text)

		cascade_specs = self._session_cascade_specs(channel_user_id, cursor)
		mission_id = f"telegram:{channel_user_id}"
		payload = {
			"prompt": prompt,
			"cascade": cascade_specs,
			"title": f"telegram {text[:40]}",
			"telegram_channel_user_id": channel_user_id,
			"telegram_chat_id": channel,
		}
		queue = CognitiveQueueManager()
		try:
			job_id = queue.enqueue_task(
				source="agentic_job",
				payload=payload,
				priority=7,
				mission_id=mission_id,
			)
		except Exception as e:
			logger.error(f"[{msg_ids}] Heavy path enqueue failed: {e}")
			if channel != "system":
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(channel, channel_user_id, None, json.dumps({"text": f"⚠️ No se pudo encolar la misión: {e}"})),
				)
			for m_id in msg_ids:
				cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (m_id,))
			conn.commit()
			conn.close()
			return

		logger.info(f"[{msg_ids}] Heavy path enqueued: job={job_id}")
		if channel != "system":
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": "⏳ En cola, te aviso cuando termine."})),
			)
		for m_id in msg_ids:
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (m_id,))
		conn.commit()
		conn.close()

	def _check_telegram_jobs(self) -> None:
		"""Fase 2 delivery: en cada pulse busca jobs Telegram COMPLETED/FRUSTRATED
		pendientes de entrega y los escribe al outbox (D18/D19).

		- mission_id prefijo `telegram:` (D18).
		- Solo COMPLETED/FRUSTRATED (no existe FAILED en la cola — v0.9).
		- Dedup: tras entregar, `set_checkpoint_key('telegram_delivered', True)`.
		"""
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue = CognitiveQueueManager()
		try:
			jobs = queue.list_tasks(statuses=["COMPLETED", "FRUSTRATED"], mission_prefix="telegram:", limit=50)
		except Exception as e:
			logger.error(f"[TelegramJobs] list_tasks failed: {e}")
			return

		for job in jobs:
			job_id = job["id"]
			detail = queue.get_task(job_id)
			if not detail:
				continue
			checkpoint = detail.get("checkpoint_data") or {}
			if checkpoint.get("telegram_delivered"):
				continue  # D19: ya entregado (worker reiniciado no re-entrega)
			channel_user_id = (detail.get("payload") or {}).get("telegram_channel_user_id")
			channel = (detail.get("payload") or {}).get("telegram_chat_id") or "telegram"
			if not channel_user_id:
				continue

			if detail.get("status") == "COMPLETED":
				response = (checkpoint.get("response") or "").strip()
				text = response or "✅ Misión completada (sin respuesta de texto)."
			else:  # FRUSTRATED
				err = detail.get("error_log") or "fallo del driver tras 3 intentos"
				text = f"⚠️ La misión falló tras los reintentos: {err}"

			conn = get_connection()
			try:
				conn.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(channel, channel_user_id, None, json.dumps({"text": text})),
				)
				conn.commit()
			except Exception as e:
				logger.error(f"[TelegramJobs] outbox insert failed for {job_id}: {e}")
				conn.close()
				continue
			conn.close()

			try:
				queue.set_checkpoint_key(job_id, "telegram_delivered", True)
			except Exception as e:
				logger.warning(f"[TelegramJobs] set_checkpoint_key failed for {job_id}: {e}")


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	import sqlite3

	worker = IDEWorker()
	worker.run()
