"""`memento_registry.json` (RFC-002 §5.3) + hilo prev/next por fuente (SHOULD 12).

Mismo directorio (`get_data_dir()`) y envoltorio `{registry, last_run, stats}`
que el retirado `chronicle_daily_registry.json` (2026-09-11). Clave: `{source:
{session_id: {dir, month, created_at, rendered_at, message_count, step_count,
body_chars, has_splits, memento_hash, prev_session, next_session}}}` —
`memento_hash` es el ancla del contrato de invalidación §4.5.1; `created_at`
alimenta el hilo.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.memento.render import update_frontmatter_links


def _default_state() -> Dict[str, Any]:
	return {"registry": {}, "last_run": None, "stats": {"total_sessions": 0}}


class MementoRegistry:
	def __init__(self, path: Optional[Path] = None):
		if path is None:
			from red_pill.core.paths import get_data_dir

			path = get_data_dir() / "memento_registry.json"
		self.path = Path(path)
		self._lock = threading.RLock()
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

	def is_rendered(self, session_id: str, sources: Optional[List[str]] = None) -> bool:
		"""¿La sesión aparece renderizada en Memento?

		Indexa `sid` crudo y `source:sid` (el registry usa la forma con prefijo en
		algunas fuentes). `sources` acota la búsqueda a esas fuentes — necesario
		para el janitor de Telegram: UUIDs crudos se repiten entre fuentes
		(p.ej. `antigravity` guarda uuids crudos), así que mirar TODAS daría
		falsos positivos y borraría una sesión de Telegram no renderizada.
		"""
		sid = str(session_id)
		if not sid:
			return False
		reg = self.state.get("registry") or {}
		if sources is not None:
			items = [(s, reg.get(s, {})) for s in sources]
		else:
			items = list(reg.items())
		for source, sessions in items:
			if not isinstance(sessions, dict):
				continue
			if sid in sessions or f"{source}:{sid}" in sessions:
				return True
		return False

	def upsert(self, source: str, session_id: str, entry: Dict[str, Any]) -> None:
		sessions = self.sessions_of(source)
		if session_id not in sessions:
			self.state["stats"]["total_sessions"] = int(self.state["stats"].get("total_sessions", 0)) + 1
		sessions.setdefault(session_id, {}).update(entry)

	def save(self) -> None:
		"""Escritura atómica: tmp + flush + fsync + os.replace bajo lock.

		El lock protege hilos que comparten instancia; la coordinación
		entre procesos queda delegada a la arquitectura single-writer.
		"""
		with self._lock:
			self.state["last_run"] = datetime.now(timezone.utc).isoformat()
			self.path.parent.mkdir(parents=True, exist_ok=True)
			payload = json.dumps(self.state, indent=2, ensure_ascii=False)
			fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
			tmp = Path(tmp_name)
			try:
				with os.fdopen(fd, "w", encoding="utf-8") as f:
					f.write(payload)
					f.flush()
					os.fsync(f.fileno())
				os.replace(tmp, self.path)
			except Exception:
				try:
					tmp.unlink(missing_ok=True)
				except Exception:
					pass
				raise


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
