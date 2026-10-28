"""
Ferrari Plugin 12 — Session Sync (RFC_CONSCIENCIA, Fase 2 / D16)
==================================================================
Digest GLOBAL de la sala de guerra: lo que un agente necesita al abrir turno
para saber quién más está vivo y en qué anda.

Tres modos (config `SESSION_SYNC_MODE`, default `silent`):
	- silent  → "" (sin coste, sin ruido, cero I/O). DEFAULT.
	- minimal → una sola línea: nº de OTRAS sesiones vivas + turno global.
	- header  → bloque compacto: por misión, las sesiones vivas (origen, rol,
	in_flight) + turno global + aviso de eventos/notas pendientes (barato).

Regla de coste (presupuesto p99 < 20 ms, medido en B2):
	- El digest se cachea con TTL corto (`SESSION_SYNC_TTL_S`, default 8 s).
	- Solo lecturas ya existentes y baratas: latidos (`session_liveness`, un
	`iterdir`) y registro (`SessionRegistry`, lecturas SQLite indexadas).
	Sin Qdrant, sin `opencode.db`, sin LLM, sin subprocess.
	- Cualquier fallo degrada a "" y registra a debug: este interceptor NUNCA
	puede tumbar ni frenar el turno.
	- En `silent` no se consulta NADA (el modo se resuelve antes del caché).
"""

import logging
import os
import time

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)

MODES = ("silent", "minimal", "header")
_DEFAULT_TTL_S = 8.0


def _conf(name: str, default):
	"""Lectura de config non-fatal (el pipeline no puede caer por un flag)."""
	try:
		return getattr(cfg.get_config(), name, default)
	except Exception:
		return default


def _mode() -> str:
	raw = str(_conf("SESSION_SYNC_MODE", "silent") or "silent").strip().lower()
	return raw if raw in MODES else "silent"


def _ttl_s() -> float:
	try:
		ttl = float(_conf("SESSION_SYNC_TTL_S", _DEFAULT_TTL_S))
	except (TypeError, ValueError):
		return _DEFAULT_TTL_S
	return ttl if 0.0 < ttl <= 300.0 else _DEFAULT_TTL_S


def _my_originator() -> str:
	"""`provider:session_id` de ESTA sesión (env del job/handshake); '' si no hay."""
	return str(os.getenv("REDPILL_ORIGINATOR") or "").strip()


class SessionSyncPlugin(BaseInterceptorPlugin):
	"""Digest de la sala de guerra por turnos (SILENT / MINIMAL / HEADER)."""

	def __init__(self):
		self._cache_at: float = 0.0
		self._cache_text: str = ""
		self._registry = None

	@property
	def name(self) -> str:
		return "Session Sync (Ferrari 12)"

	@property
	def timeout(self) -> float:
		# El pipeline impone `asyncio.wait_for`; con el caché y las lecturas
		# baratas el coste real es ~0. Corto a propósito: nunca frena el turno.
		return 0.5

	# ── Lecturas (seams para tests: cada una es una fuente barata) ────────
	def _get_registry(self):
		if self._registry is None:
			from red_pill.session.store import SessionRegistry

			self._registry = SessionRegistry()
		return self._registry

	def _live_signals(self) -> list:
		"""Latidos ACTIVOS de OTRAS sesiones (excluida la mía)."""
		from red_pill.core.session_liveness import list_sessions

		active_seconds = int(_conf("SESSION_ACTIVE_MIN", 10)) * 60
		mine = _my_originator()
		out = []
		for s in list_sessions():
			if not s.is_active(active_seconds=active_seconds):
				continue
			if mine and f"{s.provider}:{s.session_id}" == mine:
				continue
			out.append(s)
		return out

	def _global_turn(self) -> int:
		try:
			return int(self._get_registry().get_max_global_turn())
		except Exception as e:
			logger.debug(f"[SessionSync] global_turn no disponible: {e}")
			return 0

	def _registry_rows(self) -> dict:
		"""`originator -> fila` del registro (sin expiradas ni caducadas; {} si falla)."""
		try:
			rows = self._get_registry().list_sessions(limit=200)
		except Exception as e:
			logger.debug(f"[SessionSync] registro no disponible: {e}")
			return {}
		try:
			from red_pill.core.session_index import _registry_ttl_s

			ttl = _registry_ttl_s()
		except Exception:
			ttl = 12 * 3600.0
		now = time.time()
		out: dict = {}
		for r in rows:
			if not r or r.get("ttl_state") == "expired":
				continue
			updated = float(r.get("updated_at") or 0.0)
			if updated and now - updated > ttl:
				continue
			key = str(r.get("originator") or "")
			if key:
				out[key] = r
		return out

	def _pending_notice(self, rows: dict) -> str:
		"""Aviso de eventos pendientes en MI misión (una COUNT indexada; '' si no es barato)."""
		mine = _my_originator()
		if not mine:
			return ""
		row = rows.get(mine) or {}
		mission = str(row.get("mission_id") or "")
		if not mission:
			return ""
		try:
			since = int(row.get("last_seen_event_seq") or 0)
			n = self._get_registry().count_events(
				mission,
				since_seq=since,
				viewer_originator=mine,
				viewer_continuity_id=str(row.get("continuity_id") or ""),
			)
		except Exception as e:
			logger.debug(f"[SessionSync] pending notice failed: {e}")
			return ""
		if n <= 0:
			return ""
		from red_pill.session.store import sanitize_inline

		return f"Pendientes: {n} evento(s) nuevo(s) en misión {sanitize_inline(mission, 80)} (fetch_events / session_board)"

	# ── Digest ─────────────────────────────────────────────────────────────
	def _digest(self, mode: str) -> str:
		signals = self._live_signals()
		turn = self._global_turn()

		if mode == "minimal":
			return f"[SYNC: {len(signals)} otra(s) viva(s) · global_turn={turn}]"

		# header
		from red_pill.session.store import sanitize_inline

		rows = self._registry_rows()
		missions: dict = {}
		for s in signals:
			row = rows.get(f"{s.provider}:{s.session_id}") or {}
			mission = str(row.get("mission_id") or "(sin misión)")
			role = str(row.get("role") or "task")
			state = "en vuelo" if s.in_flight else "activa"
			age_s = max(0, int(time.time() - (s.start_mtime or time.time())))
			missions.setdefault(mission, []).append(
				f"[{sanitize_inline(s.provider, 40)}] {sanitize_inline(role, 20)} · {state} · hace {age_s}s"
			)

		lines = [f"--- SYNC: global_turn={turn} · {len(signals)} otra(s) viva(s) ---"]
		if not missions:
			lines.append("(sin otras sesiones vivas)")
		for mission, entries in sorted(missions.items()):
			lines.append(f"## {sanitize_inline(mission, 120)!r} ({len(entries)})")
			lines.extend(f"  {e}" for e in entries)
		notice = self._pending_notice(rows)
		if notice:
			lines.append(notice)
		return "\n".join(lines)

	async def execute(self, prompt: str) -> str:
		mode = _mode()
		if mode == "silent":
			# Cero coste, cero I/O: ni el caché se mira.
			return ""
		now = time.monotonic()
		if self._cache_at and (now - self._cache_at) < _ttl_s():
			return self._cache_text
		try:
			text = self._digest(mode)
		except Exception as e:
			# El interceptor NUNCA tumba el turno: degrada a silencio.
			logger.debug(f"[SessionSync] degrade a '' ({type(e).__name__}: {e})")
			text = ""
		self._cache_at, self._cache_text = now, text
		return text
