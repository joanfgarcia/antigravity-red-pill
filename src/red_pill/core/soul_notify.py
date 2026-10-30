"""Notificación al alma — aviso de fin de job (MVP TEMPORAL, ver AD-090).

Qué resuelve
------------
Un job lanzado desde una sesión viva termina y deja su reporte en el
MinionInbox (`_report_job`). Hasta ahora ese reporte **solo se veía si el
agente hacía `check_minion_inbox`**: el patrón "nadie lo abre" que el
RFC-RECIPE-001 documenta. Resultado: para una tarea larga no quedaba más
remedio que un `nohup … &` a ciegas, que además **no tiene alma** y por tanto
no puede avisar a nadie.

Esta pieza cierra el bucle: tras depositar el reporte, **avisa al alma** que
lanzó el job.

⚠️ TRANSPORTE TEMPORAL (decisión del Operador, 2026-10-28)
---------------------------------------------------------
El transporte de este módulo es **provisional**. Hoy entrega con el CLI del
arnés (`opencode run --session <id>`, el patrón probado con la sesión hermana
en E-001..E-005). **Cuando `neon-link` esté girado hacia dentro** (canal `soul`,
D-06), **esta pieza debe reapuntarse a ese canal** y el transporte CLI quedará
como fallback.

Para que el repunte sea un cambio de UNA línea y no una reescritura, todo el
transporte vive detrás de `_TRANSPORTS` + `_resolve_transport()`. Nada más en
el repo debe invocar `opencode run --session` para notificar a un alma.

Segundo consumidor del seam (Fase 5, 2026-10-28): `session/delivery.py` — el
adaptador que convierte un evento del tablón dirigido a un alma en un nudge.
Reutiliza `resolve_live_leg` y `notify_soul`; no abre otro canal.

Reglas que respeta (no las salta)
---------------------------------
- **D-07 (quién puede despertar a quién)**: un job es hijo del alma que lo
	lanzó, así que notificar a esa alma es *cadena de mando* — permitido.
- **D-09**: el aviso es **dato**, nunca una orden; no pide nada al receptor.
- **D-11**: `opencode run --session` **inyecta**; `api POST` fallaría cerrado
	y el mensaje desaparecería. Por eso se usa `run --session`.
- **No bloquea al worker**: la entrega corre en un hilo daemon con timeout. Un
	job NUNCA debe quedarse colgado esperando a que otro turno termine. Excepción
	que es en realidad una corrección: un llamante **efímero** (la CLI) sí debe
	esperar con `wait_for_deliveries()` antes de salir, porque el hilo daemon
	muere con el proceso y el nudge se perdería en silencio.

Non-fatal por diseño: cualquier fallo se registra y se ignora. Perder un aviso
es malo; tumbar el runner por un aviso, peor.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Env para apagar el aviso (p.ej. en tests o en runs masivos del scheduler).
ENV_DISABLE = "REDPILL_SOUL_NOTIFY_DISABLE"
# Env para forzar transporte: "cli" (MVP) | "neon_link" (futuro).
ENV_TRANSPORT = "REDPILL_SOUL_NOTIFY_TRANSPORT"
# Timeout de la entrega (segundos). Acota el hilo daemon.
DELIVERY_TIMEOUT_S = 120.0
# NOTA (2026-10-28): aquí vivía un TTL de frescura en HORAS para decidir si un
# leg era despertable. Se retiró: la alcanzabilidad del alma la gobierna
# `ttl_state` (presencia), no la edad. Detalle en `resolve_live_leg`.


# ── Resolución del cuerpo vivo ───────────────────────────────────────────────


def resolve_live_leg(continuity_id: str) -> Optional[str]:
	"""`continuity_id` (alma) → `provider:session_id` del cuerpo a avisar, o None.

	**Un alma idle también se puede despertar.** Este era el fallo del primer
	MVP: exigir `is_active()` impedía avisar a una sesión entre turnos — que es
	exactamente el caso normal (lanzas un job, te vas, termina). Verificado el
	2026-10-28: el job terminó a las 12:34 y el turno de la sesión había acabado
	a las 12:31 → `is_active=False` → el aviso nunca se entregó.

	Regla (D-05: la dirección es el alma, el cuerpo se resuelve por **presencia**):

	1. **Prefiere** un cuerpo con turno en vuelo: llega antes y sin despertar.
	2. Si no hay, usa el leg con **`ttl_state='active'`** — el cuerpo VIGENTE del
		alma. Ese estado **no caduca por tiempo**: solo cambia si el alma migra de
		cuerpo (`activate_leg` marca los anteriores como `expired`) o si se cierra
		el leg. Por eso un DAG pausado **dos días** sigue siendo avisables: el
		caso de uso que motivó esto (parar para entrenar BIT y retomar después).
	3. Sin leg `active` → no hay push; el reporte queda en el inbox (pull).

	**Por qué NO un TTL de horas** (decisión del Operador, 2026-10-28): la vida
	del *mensaje* y la alcanzabilidad del *alma* son dos relojes distintos. Un TTL
	por horas castigaba justo el uso legítimo (pausar el DAG días para dar
	prioridad a otra cosa) y, peor, era un segundo criterio que contradecía el que
	el registro ya mantiene. Si la edad no gobierna la presencia, no debe gobernar
	el aviso.
	"""
	if not continuity_id:
		return None

	try:
		from red_pill.core.session_liveness import list_sessions
		from red_pill.session.store import SessionRegistry

		legs = SessionRegistry().get_by_continuity(continuity_id)
	except Exception as e:  # registro inaccesible: no hay a quién avisar
		logger.debug(f"[soul-notify] registro no disponible: {e}")
		return None
	if not legs:
		return None

	def _originator(leg: dict) -> str:
		orig = str(leg.get("originator") or "").strip()
		return orig if orig and ":" in orig else ""

	# 1) Cuerpo con turno en vuelo (el más reciente de los activos).
	active_turn = {s.session_id for s in list_sessions() if s.is_active()}
	for leg in legs:  # ordenados por updated_at DESC
		orig = _originator(leg)
		if orig and orig.partition(":")[2] in active_turn:
			return orig

	# 2) Cuerpo VIGENTE del alma (presencia, no edad).
	for leg in legs:
		orig = _originator(leg)
		if orig and str(leg.get("ttl_state") or "") == "active":
			logger.info(f"[soul-notify] alma {continuity_id[:8]} idle; se despertará {orig} (ttl_state=active)")
			return orig

	return None


# ── Transportes (SEAM ÚNICO PARA EL REPUNTE A NEON-LINK) ─────────────────────

# Hilos de entrega en vuelo. Un llamante EFÍMERO (la CLI, un job de un solo paso
# que termina nada más avisar) se llevaría el nudge por delante al salir: los
# hilos daemon mueren con el proceso y el estado de entrega diría "entregado" en
# falso. Se guardan aquí para que ese llamante pueda `wait_for_deliveries()`.
_inflight: set = set()
_inflight_lock = threading.Lock()


def pending_deliveries() -> int:
	"""Cuántas entregas siguen en vuelo (diagnóstico y espera de llamantes cortos)."""
	with _inflight_lock:
		return len(_inflight)


def wait_for_deliveries(timeout_s: float = DELIVERY_TIMEOUT_S) -> bool:
	"""Espera a que las entregas en vuelo terminen. True si quedó limpio.

	No la llama el worker (que vive y no debe bloquearse); la llama quien sí es
	efímero — hoy, `red-pill session deliver`. Con `timeout_s` se acota: si el
	receptor no contesta, se sale y se registra el aviso pendiente, que es lo que
	pasaba de todos modos con el hilo daemon, pero ahora sin mentirle al que mira.
	"""
	deadline = time.monotonic() + max(0.0, float(timeout_s))
	while True:
		with _inflight_lock:
			threads = list(_inflight)
		if not threads:
			return True
		budget = deadline - time.monotonic()
		if budget <= 0:
			logger.warning(f"[soul-notify] {len(threads)} entrega(s) siguen en vuelo; se abandona la espera")
			return False
		threads[0].join(min(budget, 5.0))


# Último fallo del transporte, para que el emisor sepa POR QUÉ no salió (antes se
# perdía: `send` decía "park (transport_refused)" y nadie sabía más).
_last_error: str = ""


def _set_last_error(value: str) -> None:
	global _last_error
	_last_error = str(value or "")


def last_error() -> str:
	"""Motivo del último fallo de entrega (cadena vacía si no hubo)."""
	return _last_error


# Rutas donde vive el binario cuando el PATH no lo trae (systemd, jobs, cron).
def opencode_binary() -> Optional[str]:
	"""Ruta del CLI de opencode. Delegado en `core.paths` (CONVENTIONS §7).

	Bajo systemd el PATH es mínimo y el binario vive en el HOME del usuario: aquí
	solo se envuelve el resolutor canónico y se normaliza el "no está".
	"""
	from red_pill.core.paths import find_harness_binary

	return find_harness_binary("opencode") or None


def _deliver_cli(session_id: str, text: str) -> bool:
	"""Transporte MVP: inyecta un turno con el CLI del arnés.

	`opencode run --session` es la ruta que **inyecta** (D-11). Se lanza en un
	hilo daemon para no bloquear al worker: la entrega implica un turno del
	receptor y puede tardar. Quien no pueda permitirse ese hilo vivo hasta el fin
	(proceso efímero) usa `wait_for_deliveries` antes de salir.

	Devuelve True cuando el proceso de entrega **arrancó**, no cuando el receptor
	lo leyó: el `rc` se registra pero ya no vuelve al llamante. Esa es la
	limitación honesta del seam; la confirmación real es terreno del canal `soul`.
	"""
	exe = opencode_binary()
	if exe is None:
		# No es un fallo del mensaje: es el ENTORNO. Bajo systemd el PATH es mínimo y
		# `~/.opencode/bin` no está (incidente 2026-10-30: un aviso entre hermanas se
		# quedó `pending` y el Operador tuvo que ir a decírselo a mano). Se registra
		# como error —no warning— para que el motivo llegue al emisor.
		_set_last_error("opencode_no_encontrado")
		logger.error("[soul-notify] binario `opencode` no encontrado (¿systemd sin PATH?); aviso NO entregado")
		return False

	def _run() -> None:
		try:
			res = subprocess.run(
				[exe, "run", "--session", session_id, text],
				capture_output=True,
				text=True,
				timeout=DELIVERY_TIMEOUT_S,
			)
			if res.returncode != 0:
				logger.warning(f"[soul-notify] entrega falló (rc={res.returncode}): {res.stderr[:200]}")
		except Exception as e:
			logger.warning(f"[soul-notify] entrega falló: {e}")
		finally:
			with _inflight_lock:
				_inflight.discard(threading.current_thread())

	def _traced() -> None:
		with _inflight_lock:
			_inflight.add(threading.current_thread())
		_run()

	_set_last_error("")
	threading.Thread(target=_traced, name=f"soul-notify-{session_id[:12]}", daemon=True).start()
	return True


def _deliver_neon_link(session_id: str, text: str) -> bool:
	"""Transporte FUTURO: canal `soul` de neon-link (D-06).

	Pendiente de implementar cuando neon-link mire hacia dentro. Debe depositar
	el mensaje como evento (`mission_events`) y dejar que el broker guarde solo
	su estado de entrega. **No implementar aquí un segundo buzón.**
	"""
	logger.info("[soul-notify] transporte neon_link no disponible aún; sin entrega")
	return False


# El repunte a neon-link es cambiar cuál de estos es el DEFAULT.
_TRANSPORTS = {
	"cli": _deliver_cli,
	"neon_link": _deliver_neon_link,
}
_DEFAULT_TRANSPORT = "cli"  # ← TEMPORAL (ver AD-090); pasará a "neon_link"


def _resolve_transport() -> str:
	forced = str(os.getenv(ENV_TRANSPORT) or "").strip().lower()
	if forced in _TRANSPORTS:
		return forced
	return _DEFAULT_TRANSPORT


# ── API pública ─────────────────────────────────────────────────────────────


# Providers que cada transporte sabe entregar. `cli` habla `opencode run
# --session`, así que solo entiende cuerpos de opencode. Un leg de job (`dag:`)
# o de otro arnés NO es entregable por esta vía.
_DELIVERABLE_BY_TRANSPORT = {
	"cli": frozenset({"opencode"}),
	"neon_link": frozenset({"opencode", "claude_code", "pi", "telegram"}),
}


def _is_deliverable_leg(leg: Optional[str], transport: str) -> bool:
	"""¿Es `leg` un cuerpo que este transporte puede entregar de verdad?

	Evita el fallo silencioso de pasar un leg informativo (`dag:<uuid>`,
	`job:<id>`) a un CLI que espera un `session_id` del arnés.
	"""
	if not leg or ":" not in str(leg):
		return False
	provider, _, session_id = str(leg).partition(":")
	if not session_id:
		return False
	allowed = _DELIVERABLE_BY_TRANSPORT.get(transport)
	if allowed is None:
		return False
	return provider in allowed


def notify_disabled() -> bool:
	"""True si el aviso está apagado por env. Único juez del kill switch.

	Lo usa `notify_soul` y también `session/delivery.py` (el adaptador de eventos
	del tablón, Fase 5): si el interruptor se consulta en dos sitios pueden
	divergir y un lado puede quedar desprotegido.
	"""
	return str(os.getenv(ENV_DISABLE) or "").strip().lower() in {"1", "true", "yes", "on"}


def build_job_notice(title: str, source: str, status: str, content: str, result_path: str = "") -> str:
	"""Texto del aviso. Es DATO: no pide nada ni manda nada (D-09)."""
	suffix = f"\n[result: {result_path}]" if result_path else ""
	return (
		"[AVISO AUTOMÁTICO · fin de job · DATO, no orden]\n"
		f"Job '{title}' ({source}) → {status}: {content}{suffix}\n"
		"No requiere respuesta. Si el resultado importa, léelo desde el job."
	)


def notify_soul(
	continuity_id: str,
	text: str,
	*,
	originator: Optional[str] = None,
) -> bool:
	"""Avisa al alma `continuity_id` por el transporte activo. Non-fatal.

	Devuelve True si se encoló una entrega. Un `False` no es un error del job:
	el reporte ya está en el MinionInbox (pull siempre funciona).
	"""
	if not continuity_id:
		return False
	if notify_disabled():
		return False
	transport = _resolve_transport()
	fn = _TRANSPORTS.get(transport)
	if fn is None:
		return False
	# El `originator` que llega puede ser el leg del JOB (`dag:<uuid>`), no el
	# cuerpo de un arnés. Pasarlo tal cual a `opencode run --session` reventaba
	# con `Expected a string starting with "ses"` y el aviso se perdía en
	# silencio (incidente 2026-10-28, job e328f02f: el dag_job escribe su propio
	# `leg_originator` en el checkpoint y `job_identity` lo devuelve).
	# Solo se acepta como cuerpo un provider que el transporte sepa entregar;
	# en cualquier otro caso se resuelve por alma, que es la dirección real.
	leg = originator if _is_deliverable_leg(originator, transport) else None
	if leg is None:
		leg = resolve_live_leg(continuity_id)
		if leg is not None and not _is_deliverable_leg(leg, transport):
			leg = None
	if not leg or ":" not in leg:
		logger.debug(f"[soul-notify] alma {continuity_id[:8]} sin cuerpo entregable; queda en el inbox (pull)")
		return False
	_, _, session_id = leg.partition(":")
	if not session_id:
		return False
	try:
		return bool(fn(session_id, text))
	except Exception as e:
		logger.warning(f"[soul-notify] transporte {transport} falló: {e}")
		return False
