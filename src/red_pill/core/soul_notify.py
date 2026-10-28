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

Reglas que respeta (no las salta)
---------------------------------
- **D-07 (quién puede despertar a quién)**: un job es hijo del alma que lo
  lanzó, así que notificar a esa alma es *cadena de mando* — permitido.
- **D-09**: el aviso es **dato**, nunca una orden; no pide nada al receptor.
- **D-11**: `opencode run --session` **inyecta**; `api POST` fallaría cerrado
  y el mensaje desaparecería. Por eso se usa `run --session`.
- **No bloquea al worker**: la entrega corre en un hilo daemon con timeout. Un
  job NUNCA debe quedarse colgado esperando a que otro turno termine.

Non-fatal por diseño: cualquier fallo se registra y se ignora. Perder un aviso
es malo; tumbar el runner por un aviso, peor.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Env para apagar el aviso (p.ej. en tests o en runs masivos del scheduler).
ENV_DISABLE = "REDPILL_SOUL_NOTIFY_DISABLE"
# Env para forzar transporte: "cli" (MVP) | "neon_link" (futuro).
ENV_TRANSPORT = "REDPILL_SOUL_NOTIFY_TRANSPORT"
# Timeout de la entrega (segundos). Acota el hilo daemon.
DELIVERY_TIMEOUT_S = 120.0


# ── Resolución del cuerpo vivo ───────────────────────────────────────────────


def resolve_live_leg(continuity_id: str) -> Optional[str]:
	"""`continuity_id` (alma) → `provider:session_id` del cuerpo **vivo**, o None.

	Un alma puede haber vivido en varios cuerpos (reencarnaciones); solo tiene
	sentido avisar si hay un cuerpo vivo que pueda recibir el turno. Se prefiere
	el cuerpo con latido (`.start` reciente) y, si hay varios, el más reciente.
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

	active = {s.session_id for s in list_sessions() if s.is_active()}
	# Prioridad: cuerpo con latido activo; si ninguno, el más reciente del registro.
	for leg in legs:  # ya vienen ordenados por updated_at DESC
		originator = str(leg.get("originator") or "").strip()
		if not originator or ":" not in originator:
			continue
		_, _, sid = originator.partition(":")
		if sid in active:
			return originator
	return None


# ── Transportes (SEAM ÚNICO PARA EL REPUNTE A NEON-LINK) ─────────────────────


def _deliver_cli(session_id: str, text: str) -> bool:
	"""Transporte MVP: inyecta un turno con el CLI del arnés.

	`opencode run --session` es la ruta que **inyecta** (D-11). Se lanza en un
	hilo daemon para no bloquear al worker: la entrega implica un turno del
	receptor y puede tardar.
	"""
	exe = shutil.which("opencode")
	if exe is None:
		logger.warning("[soul-notify] opencode no está en PATH; aviso no entregado")
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

	threading.Thread(target=_run, name=f"soul-notify-{session_id[:12]}", daemon=True).start()
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
	if str(os.getenv(ENV_DISABLE) or "").strip().lower() in {"1", "true", "yes", "on"}:
		return False
	leg = originator or resolve_live_leg(continuity_id)
	if not leg or ":" not in leg:
		logger.debug(f"[soul-notify] alma {continuity_id[:8]} sin cuerpo vivo; queda en el inbox (pull)")
		return False
	_, _, session_id = leg.partition(":")
	if not session_id:
		return False
	transport = _resolve_transport()
	fn = _TRANSPORTS.get(transport)
	if fn is None:
		return False
	try:
		return bool(fn(session_id, text))
	except Exception as e:
		logger.warning(f"[soul-notify] transporte {transport} falló: {e}")
		return False
