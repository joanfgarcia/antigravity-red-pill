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

Segundo transporte (F6, 2026-10-30): `claude_socket`, el socket de mensajería
por sesión de Claude Code. El transporte se elige por el arnés del cuerpo
(`_PROVIDER_TRANSPORT`): opencode sigue en `cli` y claude_code va por su socket.
`REDPILL_SOUL_NOTIFY_TRANSPORT` sigue forzando uno para todos.

Reglas que respeta (no las salta)
---------------------------------
- **D-07 (quién puede despertar a quién)**: un job es hijo del alma que lo
	lanzó, así que notificar a esa alma es *cadena de mando* — permitido.
- **D-09**: el aviso es **dato**, nunca una orden; no pide nada al receptor.
- **D-11**: `opencode run --session` **inyecta**; `api POST` fallaría cerrado
	y el mensaje desaparecería. Por eso se usa `run --session`.
- **No bloquea al worker ni hereda su vida**: el CLI se lanza como hijo en su
	propia sesión de procesos y sin timeout. Ni el llamante espera al turno del
	receptor, ni el turno muere si el llamante (un MCP directo, la CLI) sale antes.
	Antes era un hilo daemon con `timeout=120 s`: con un llamante efímero el turno
	moría a medias y el estado ya decía «entregado» (2026-10-30).

Non-fatal por diseño: cualquier fallo se registra y se ignora. Perder un aviso
es malo; tumbar el runner por un aviso, peor.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Env para apagar el aviso (p.ej. en tests o en runs masivos del scheduler).
ENV_DISABLE = "REDPILL_SOUL_NOTIFY_DISABLE"
# Env para forzar transporte: "cli" (MVP) | "neon_link" (futuro).
ENV_TRANSPORT = "REDPILL_SOUL_NOTIFY_TRANSPORT"
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

# Último fallo del transporte, para que el emisor sepa POR QUÉ no salió (antes se
# perdía: `send` decía "park (transport_refused)" y nadie sabía más).
_last_error: str = ""


def _set_last_error(value: str) -> None:
	global _last_error
	_last_error = str(value or "")


def last_error() -> str:
	"""Motivo del último fallo de entrega (cadena vacía si no hubo)."""
	return _last_error


# Rastro de la última entrega que lo tenga (ruta del fichero de salida del CLI).
_last_trace: str = ""


def _set_last_trace(value: str) -> None:
	global _last_trace
	_last_trace = str(value or "")


def last_trace() -> str:
	"""Dónde mirar qué pasó con la última entrega (cadena vacía si no deja fichero)."""
	return _last_trace


# Rutas donde vive el binario cuando el PATH no lo trae (systemd, jobs, cron).
def opencode_binary() -> Optional[str]:
	"""Ruta del CLI de opencode. Delegado en `core.paths` (CONVENTIONS §7).

	Bajo systemd el PATH es mínimo y el binario vive en el HOME del usuario: aquí
	solo se envuelve el resolutor canónico y se normaliza el "no está".
	"""
	from red_pill.core.paths import find_harness_binary

	return find_harness_binary("opencode") or None


# Errores de transporte que significan «ese cuerpo ya no existe»: el leg se caduca
# para que el tablón deje de ofrecerlo (si vuelve, su handshake lo reactiva).
STALE_LEG = "stale_leg"
_STALE_ERRORS = frozenset({STALE_LEG, "claude_socket_ausente"})
OPENCODE_PROBE_TIMEOUT_S = 15.0


def opencode_session_exists(session_id: str, *, exe: Optional[str] = None) -> Optional[bool]:
	"""¿Existe la sesión opencode `session_id`? True/False, o None si no se sabe.

	Sonda de solo lectura: `opencode session export <id>` contra el servicio de
	fondo del arnés (sin la auth del desktop). rc=0 → existe; rc≠0 con «Session not
	found» → no existe; cualquier otra cosa (timeout, servicio caído) → None. La
	tabla `session` de `opencode.db` NO sirve: en V2 está obsoleta.
	"""
	exe = exe or opencode_binary()
	if not exe or not session_id:
		return None
	try:
		res = subprocess.run(
			[exe, "session", "export", session_id],
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
			text=True,
			timeout=OPENCODE_PROBE_TIMEOUT_S,
		)
	except (OSError, subprocess.TimeoutExpired) as e:
		logger.warning(f"[soul-notify] la sonda de {session_id[:16]} no respondió: {e}")
		return None
	if res.returncode == 0:
		return True
	if "session not found" in (res.stderr or "").lower():
		return False
	logger.warning(f"[soul-notify] sonda de {session_id[:16]} ambigua (rc={res.returncode}): {(res.stderr or '')[:200]}")
	return None


def _expire_stale_leg(leg: str) -> None:
	"""Caduca el leg de un cuerpo que ya no existe. Non-fatal."""
	try:
		from red_pill.session.store import SessionRegistry

		if SessionRegistry().unregister_session(leg):
			logger.info(f"[soul-notify] leg {leg[:40]} caducado: el cuerpo ya no existe")
	except Exception as e:
		logger.warning(f"[soul-notify] no se pudo caducar {leg[:40]}: {e}")


def _new_trace(session_id: str) -> Path:
	"""Fichero de rastro de UNA entrega por CLI: lo que el emisor puede abrir después."""
	from red_pill.core.paths import get_log_dir

	directory = get_log_dir() / "soul_notify"
	directory.mkdir(parents=True, exist_ok=True)
	safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:40]
	return directory / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.log"


def _watch_cli(proc: "subprocess.Popen", session_id: str, trace: Path) -> None:
	"""Recoge el `rc` del hijo para el log y evita el zombi. Nunca lo mata."""
	try:
		rc = proc.wait()
	except Exception as e:
		logger.warning(f"[soul-notify] no se pudo esperar la entrega a {session_id[:16]}: {e}")
		return
	if rc != 0:
		logger.warning(f"[soul-notify] la entrega a {session_id[:16]} acabó con rc={rc}; rastro en {trace}")


def _deliver_cli(session_id: str, text: str) -> bool:
	"""Transporte MVP: inyecta un turno con el CLI del arnés.

	`opencode run --session` es la ruta que **inyecta** (D-11). El turno que abre
	es del RECEPTOR, así que la entrega no puede depender de la vida de quien la
	lanza (incidente 2026-10-30: con el MCP directo de Claude, el llamante era el
	proceso del MCP; el hijo y su hilo murieron con él a mitad del turno):

	- El hijo arranca en su **propia sesión de procesos** (`start_new_session`) y
		**sin timeout**: sobrevive al llamante y nadie corta el turno a medias.
	- Su salida va a un **fichero de rastro** (`last_trace()`): el log del
		llamante puede morir con él, el rastro no.
	- Un hilo daemon solo espera al hijo para anotar el `rc` y no dejar un zombi.

	Devuelve True cuando el hijo **arrancó**, no cuando el receptor lo leyó, y
	el `rc` no prueba nada. Por eso delivery lo cierra como `handed_off`, no
	como `delivered`.

	Antes de inyectar se comprueba que la sesión EXISTE (`opencode_session_exists`):
	`run --session <id desconocido>` no falla, **crea una sesión con ese id** y le
	hace un turno que nadie mira (medido 2026-10-30 con `ses_doesnotexist…`).
	Inyectar a ciegas fabrica fantasmas.
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
	exists = opencode_session_exists(session_id, exe=exe)
	if exists is False:
		_set_last_error(STALE_LEG)
		logger.warning(f"[soul-notify] la sesión opencode {session_id[:16]} no existe; no se inyecta")
		return False
	if exists is None:
		# Sin respuesta de la sonda no se sabe si el `run` crearía un fantasma: no
		# se inyecta, pero tampoco se caduca nada. El pull sigue ahí.
		_set_last_error("opencode_sonda_fallida")
		return False
	try:
		trace = _new_trace(session_id)
		with open(trace, "ab") as out:
			out.write(f"# soul-notify cli → opencode:{session_id} · {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n".encode("utf-8"))
			out.flush()
			proc = subprocess.Popen(
				[exe, "run", "--session", session_id, text],
				stdin=subprocess.DEVNULL,
				stdout=out,
				stderr=subprocess.STDOUT,
				start_new_session=True,
			)
	except OSError as e:
		_set_last_error("opencode_no_arranca")
		logger.error(f"[soul-notify] no se pudo lanzar la entrega a {session_id[:16]}: {e}")
		return False
	_set_last_error("")
	_set_last_trace(str(trace))
	threading.Thread(target=_watch_cli, args=(proc, session_id, trace), name=f"soul-notify-{session_id[:12]}", daemon=True).start()
	return True


# Directorios donde Claude Code crea sus sockets de mensajería (los mismos que
# acepta el propio binario: `/run/user/<uid>/cc-socks`, `/tmp/cc-socks[-<uid>]`).
_CLAUDE_SOCKET_DIR = re.compile(r"^(/run/user/\d+/cc-socks|/tmp/cc-socks(-\d+)?|/private/tmp/cc-socks(-\d+)?)$")
CLAUDE_SOCKET_TIMEOUT_S = 5.0


def claude_messaging_socket(session_id: str) -> Optional[str]:
	"""Socket de mensajería de la sesión Claude Code `session_id`, validado, o None.

	La ruta la deja el hook `redpill_turn_start.py` en el bridge por sesión. Solo
	se acepta un socket de verdad, del mismo UID y dentro de un directorio
	`cc-socks`: el bridge es un fichero de estado y no debe poder apuntar el
	transporte a cualquier socket del sistema. El motivo del rechazo queda en
	`last_error()`.
	"""
	import stat

	from red_pill.core.bridge import read_session_bridge

	entry = read_session_bridge("claude_code", session_id) or {}
	path = str(entry.get("messaging_socket") or "").strip()
	if not path:
		_set_last_error("claude_sin_socket_en_bridge")
		return None
	if not _CLAUDE_SOCKET_DIR.match(os.path.dirname(path)) or not path.endswith(".sock"):
		_set_last_error("claude_socket_fuera_de_cc_socks")
		return None
	try:
		st = os.stat(path)
	except OSError:
		# La sesión que lo abrió ya no vive (o reanudó con otro proceso y aún no
		# ha empezado turno para reescribir el bridge).
		_set_last_error("claude_socket_ausente")
		return None
	if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
		_set_last_error("claude_socket_no_valido")
		return None
	return path


def _deliver_claude_socket(session_id: str, text: str) -> bool:
	"""Inyecta un turno en una sesión de Claude Code por su socket de mensajería (F6).

	Es la vía oficial de mensajería entre sesiones de Claude Code: una línea
	NDJSON `{"type":"user",...}` por el socket UDS de la sesión. Si la sesión
	está en un turno, el mensaje entra en ese turno; si está idle, Claude abre uno
	nuevo (verificado 2026-10-30 en el desktop, CLI 2.1.309). El arnés lo
	enmarca como mensaje de otra sesión, no del Operador, y no concede permisos:
	encaja con D-09 sin hacer nada.

	Síncrono, sin hilo: escribir en un socket local no espera al turno del
	receptor. Como en `cli`, True significa que el socket **aceptó los bytes**, no
	que se leyera; la política de entrada del receptor (`crossSessionInbound`)
	todavía puede retenerlo.
	"""
	import json
	import socket

	path = claude_messaging_socket(session_id)
	if path is None:
		logger.info(f"[soul-notify] claude {session_id[:8]}: {last_error()}; queda en el inbox (pull)")
		return False
	line = json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"
	try:
		with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
			sock.settimeout(CLAUDE_SOCKET_TIMEOUT_S)
			sock.connect(path)
			sock.sendall(line.encode("utf-8"))
			sock.shutdown(socket.SHUT_WR)
	except OSError as e:
		_set_last_error("claude_socket_rechazo")
		logger.warning(f"[soul-notify] socket de claude {session_id[:8]} rechazó la entrega: {e}")
		return False
	_set_last_error("")
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
	"claude_socket": _deliver_claude_socket,
	"neon_link": _deliver_neon_link,
}
_DEFAULT_TRANSPORT = "cli"  # ← TEMPORAL (ver AD-090); pasará a "neon_link"
# Transporte propio de un arnés cuando no hay override: cada cuerpo se entrega
# por el punto de inyección que su arnés tiene de verdad.
_PROVIDER_TRANSPORT = {"claude_code": "claude_socket"}


def _resolve_transport(provider: str = "") -> str:
	forced = str(os.getenv(ENV_TRANSPORT) or "").strip().lower()
	if forced in _TRANSPORTS:
		return forced
	return _PROVIDER_TRANSPORT.get(str(provider or ""), _DEFAULT_TRANSPORT)


def _leg_provider(leg: Optional[str]) -> str:
	return str(leg or "").partition(":")[0]


# ── API pública ─────────────────────────────────────────────────────────────


# Providers que cada transporte sabe entregar. `cli` habla `opencode run
# --session`, así que solo entiende cuerpos de opencode. Un leg de job (`dag:`)
# o de otro arnés NO es entregable por esta vía.
_DELIVERABLE_BY_TRANSPORT = {
	"cli": frozenset({"opencode"}),
	"claude_socket": frozenset({"claude_code"}),
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
	# El `originator` que llega puede ser el leg del JOB (`dag:<uuid>`), no el
	# cuerpo de un arnés. Pasarlo tal cual a `opencode run --session` reventaba
	# con `Expected a string starting with "ses"` y el aviso se perdía en
	# silencio (incidente 2026-10-28, job e328f02f: el dag_job escribe su propio
	# `leg_originator` en el checkpoint y `job_identity` lo devuelve).
	# Solo se acepta como cuerpo un provider que el transporte sepa entregar;
	# en cualquier otro caso se resuelve por alma, que es la dirección real.
	# El transporte depende del arnés del cuerpo, así que se decide por leg.
	leg = originator if _is_deliverable_leg(originator, _resolve_transport(_leg_provider(originator))) else None
	if leg is None:
		leg = resolve_live_leg(continuity_id)
		if leg is not None and not _is_deliverable_leg(leg, _resolve_transport(_leg_provider(leg))):
			leg = None
	if not leg or ":" not in leg:
		logger.debug(f"[soul-notify] alma {continuity_id[:8]} sin cuerpo entregable; queda en el inbox (pull)")
		return False
	provider, _, session_id = leg.partition(":")
	if not session_id:
		return False
	transport = _resolve_transport(provider)
	fn = _TRANSPORTS.get(transport)
	if fn is None:
		return False
	try:
		_set_last_trace("")
		ok = bool(fn(session_id, text))
	except Exception as e:
		logger.warning(f"[soul-notify] transporte {transport} falló: {e}")
		return False
	if not ok and last_error() in _STALE_ERRORS:
		_expire_stale_leg(leg)
	return ok
