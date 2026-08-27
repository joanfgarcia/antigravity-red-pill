"""`memento_registry.json` (RFC-002 §5.3) + hilo prev/next por fuente (SHOULD 12).

Espejo del `chronicle_daily_registry.json`: mismo directorio (`get_data_dir()`),
mismo envoltorio `{registry, last_run, stats}`. Clave: `{source: {session_id:
{dir, month, created_at, rendered_at, message_count, step_count, body_chars,
has_splits, memento_hash, prev_session, next_session}}}` — `memento_hash` es el
ancla del contrato de invalidación §4.5.1; `created_at` alimenta el hilo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from red_pill.memento.render import update_frontmatter_links


def _default_state() -> Dict[str, Any]:
	return {"registry": {}, "last_run": None, "stats": {"total_sessions": 0}}


class MementoRegistry:
	def __init__(self, path: Optional[Path] = None):
		if path is None:
			from red_pill.core.paths import get_data_dir

			path = get_data_dir() / "memento_registry.json"
		self.path = Path(path)
		self.state = _default_state()
		if self.path.exists():
			try:
				loaded = json.loads(self.path.read_text(encoding="utf-8"))
				if isinstance(loaded, dict):
					self.state.update(loaded)
			except Exception:
				pass  # registro corrupto: se reconstruye con el próximo render (idempotente)
		for key, default in _default_state().items():
			self.state.setdefault(key, default)

	def sessions_of(self, source: str) -> Dict[str, Dict[str, Any]]:
		sessions = self.state["registry"].setdefault(source, {})
		assert isinstance(sessions, dict)
		return sessions

	def get(self, source: str, session_id: str) -> Optional[Dict[str, Any]]:
		return self.sessions_of(source).get(session_id)

	def upsert(self, source: str, session_id: str, entry: Dict[str, Any]) -> None:
		sessions = self.sessions_of(source)
		if session_id not in sessions:
			self.state["stats"]["total_sessions"] = int(self.state["stats"].get("total_sessions", 0)) + 1
		sessions.setdefault(session_id, {}).update(entry)

	def save(self) -> None:
		self.state["last_run"] = datetime.now(timezone.utc).isoformat()
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")


def recompute_chain(root: Path, registry: MementoRegistry, source: str) -> int:
	"""Recalcula el hilo prev/next de una fuente (orden: created_at del primer mensaje).

	Solo reescribe el frontmatter de los index.md cuyos vecinos cambiaron —
	el `memento_hash` (cuerpo) queda intacto, así que no dispara invalidación.
	Devuelve cuántas sesiones actualizó.
	"""
	sessions = {sid: entry for sid, entry in registry.sessions_of(source).items() if entry.get("dir")}
	ordered = sorted(sessions.items(), key=lambda kv: (kv[1].get("created_at") is None, kv[1].get("created_at") or "", kv[0]))
	session_ids = [session_id for session_id, _entry in ordered]

	updated = 0
	for i, (session_id, entry) in enumerate(ordered):
		prev_session = session_ids[i - 1] if i > 0 else None
		next_session = session_ids[i + 1] if i < len(session_ids) - 1 else None
		if entry.get("prev_session") == prev_session and entry.get("next_session") == next_session:
			continue
		index_file = root / entry["dir"] / "memento" / "index.md"
		if index_file.exists():
			update_frontmatter_links(index_file, prev_session, next_session)
		entry["prev_session"] = prev_session
		entry["next_session"] = next_session
		updated += 1
	return updated
