"""Latido de sesión — señal inicio/fin de turno (RFC-DESPERTAR-001, P4).

Cada turno deja **dos ficheros vacíos** por sesión:

- `${STATE_DIR}/sessions/live/<provider>__<session_id>.start`
- `${STATE_DIR}/sessions/live/<provider>__<session_id>.end`

El nombre codifica provider, sesión y fase; la `mtime` es la señal. Sin contenido.

Interpretación con el par:

- `.start` > `.end` (y reciente) → *alguien está tocando* (turno en vuelo).
- `.end` reciente → *alguien ha tocado*; `end - start` = duración del turno.
- solo `.start` viejo → sesión muerta a medio turno (huérfana).

Los hooks que escriben (Claude `UserPromptSubmit`/`Stop`, opencode) son
standalone y replican la resolución de `${STATE_DIR}`; este módulo es para el
kernel (índice, janitor, tools) y los tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from red_pill.core.paths import get_state_dir

LIVE_SUBDIR = "sessions/live"
PHASE_START = "start"
PHASE_END = "end"
PHASES: Tuple[str, ...] = (PHASE_START, PHASE_END)
_DELIM = "__"


def get_sessions_live_dir() -> Path:
	"""`${STATE_DIR}/sessions/live` (se crea si no existe)."""
	path = get_state_dir() / LIVE_SUBDIR
	path.mkdir(parents=True, exist_ok=True)
	return path


def _safe(token: str) -> str:
	"""Sanea un componente del nombre: sin separadores de path ni el delimitador."""
	return token.strip().replace("/", "_").replace(_DELIM, "_")


def _filename(provider: str, session_id: str, phase: str) -> str:
	return f"{_safe(provider)}{_DELIM}{_safe(session_id)}.{phase}"


def touch_session(provider: str, session_id: str, phase: str) -> Optional[Path]:
	"""Marca un latido (crea o actualiza la `mtime` del fichero vacío). Non-fatal."""
	if not provider or not session_id or phase not in PHASES:
		return None
	try:
		path = get_sessions_live_dir() / _filename(provider, session_id, phase)
		path.touch(exist_ok=True)
		return path
	except Exception:
		return None


def parse_filename(name: str) -> Optional[Tuple[str, str, str]]:
	"""`<provider>__<session>.<phase>` → `(provider, session, phase)` o None."""
	if "." not in name:
		return None
	stem, phase = name.rsplit(".", 1)
	if phase not in PHASES or _DELIM not in stem:
		return None
	provider, session = stem.split(_DELIM, 1)
	if not provider or not session:
		return None
	return provider, session, phase


@dataclass
class SessionSignal:
	provider: str
	session_id: str
	start_mtime: Optional[float] = None
	end_mtime: Optional[float] = None

	@property
	def last_mtime(self) -> Optional[float]:
		vals = [v for v in (self.start_mtime, self.end_mtime) if v is not None]
		return max(vals) if vals else None

	@property
	def in_flight(self) -> bool:
		"""Hay un `.start` sin `.end` posterior → turno abierto."""
		return self.start_mtime is not None and (self.end_mtime is None or self.start_mtime > self.end_mtime)

	def is_active(self, now: Optional[float] = None, active_seconds: int = 600) -> bool:
		"""Turno en vuelo **y** su `.start` es reciente → *alguien está tocando*."""
		now = time.time() if now is None else now
		return bool(self.in_flight and self.start_mtime is not None and (now - self.start_mtime) <= active_seconds)


def list_sessions() -> List[SessionSignal]:
	"""Lee el directorio de latidos y agrupa por `(provider, session_id)`.

	Ordenado por última actividad descendente (más reciente primero).
	"""
	live = get_sessions_live_dir()
	acc: dict = {}
	for item in live.iterdir():
		if not item.is_file():
			continue
		parsed = parse_filename(item.name)
		if not parsed:
			continue
		provider, session, phase = parsed
		try:
			mtime = item.stat().st_mtime
		except OSError:
			continue
		sig = acc.setdefault((provider, session), {PHASE_START: None, PHASE_END: None})
		sig[phase] = mtime

	out = [SessionSignal(provider=p, session_id=s, start_mtime=v[PHASE_START], end_mtime=v[PHASE_END]) for (p, s), v in acc.items()]
	out.sort(key=lambda sig: sig.last_mtime or 0.0, reverse=True)
	return out
