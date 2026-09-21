"""Registro de orígenes de sesión por provider (`session_id` → `origin`).

Cada bridge registra el origen con el que lanzó una sesión (`telegram`,
`awakening`, `user`, `job`…). Las fuentes chronicle lo consultan para no
renderizar doble una sesión que otro source ya cubre: una sesión con
`origin=telegram` la sirve el source `telegram`, sea cual sea el provider
(opencode / claude_code / pi / antigravity) que la haya ejecutado.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from red_pill.core.paths import get_state_dir

logger = logging.getLogger(__name__)

PROVIDER_OPENCODE = "opencode"
PROVIDER_CLAUDE = "claude_code"
PROVIDER_PI = "pi"
PROVIDER_ANTIGRAVITY = "antigravity"

TELEGRAM_ORIGIN = "telegram"


def get_origins_path() -> Path:
	return get_state_dir() / "session_origins.json"


def _load() -> Dict[str, Any]:
	path = get_origins_path()
	if not path.exists():
		return {}
	try:
		data = json.loads(path.read_text())
		return data if isinstance(data, dict) else {}
	except (json.JSONDecodeError, OSError):
		return {}


def _legacy_opencode_origins() -> Dict[str, Any]:
	"""Registro pre-AD-034 (`opencode_origins.json` plano) — solo lectura."""
	path = get_state_dir() / "opencode_origins.json"
	if not path.exists():
		return {}
	try:
		data = json.loads(path.read_text())
		return data if isinstance(data, dict) else {}
	except (json.JSONDecodeError, OSError):
		return {}


def record_origin(provider: str, session_id: str, origin: str) -> None:
	"""Persiste el origen de una sesión (no fatal si falla)."""
	if not provider or not session_id or not origin:
		return
	path = get_origins_path()
	try:
		data = _load()
		registry = data.get(provider)
		if not isinstance(registry, dict):
			registry = data[provider] = {}
		registry[session_id] = {"origin": origin, "ts": int(time.time())}
		path.write_text(json.dumps(data))
	except Exception as e:
		logger.warning(f"[Origins] Failed to record {origin!r} for {provider}/{session_id!r}: {e}")


def read_origins(provider: Optional[str] = None) -> Dict[str, Any]:
	"""Registro completo (`{provider: {session_id: {...}}}`) o el de un provider.

	Para `opencode` fusiona el sidecar legado (solo lectura) por compatibilidad.
	"""
	data = _load()
	if provider == PROVIDER_OPENCODE:
		legacy = _legacy_opencode_origins()
		if legacy:
			merged = dict(legacy)
			merged.update(data.get(PROVIDER_OPENCODE) or {})
			data = {**data, PROVIDER_OPENCODE: merged}
	if provider is None:
		return data
	return data.get(provider) or {}


def has_origin(provider: str, session_id: str, origin: str) -> bool:
	return (read_origins(provider).get(session_id) or {}).get("origin") == origin


def telegram_sessions(provider: str) -> Set[str]:
	"""`session_id`s del provider servidos por Telegram (los renderiza su source)."""
	return {sid for sid, meta in read_origins(provider).items() if isinstance(meta, dict) and meta.get("origin") == TELEGRAM_ORIGIN}
