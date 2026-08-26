"""Índices generados del árbol Memento (RFC-002 SHOULD 13, Fase 2).

- `<memento>/index/<source>.md`: todas las sesiones de una fuente, cronológicas
  (recupera el browsing "todas las sesiones de X" que el layout mes-primero cede).
- `<memento>/<AAAA-MM>/_index.md`: las sesiones del mes, cruzando fuentes.

Regenerables e idempotentes: se reconstruyen enteros en cada pasada del migrate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


def _entry_line(session_id: str, entry: Dict[str, Any], link_prefix: str) -> str:
	created = (entry.get("created_at") or "")[:16].replace("T", " ") or "(sin fecha)"
	marks = []
	if entry.get("reconstructed"):
		marks.append("reconstructed")
	if entry.get("has_splits"):
		marks.append("splits")
	suffix = f" · {', '.join(marks)}" if marks else ""
	return f"- {created} — [{session_id}]({link_prefix}{entry['dir']}/memento/index.md) · {entry.get('message_count', 0)} msgs{suffix}"


def _sorted_sessions(sessions: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
	rendered = [(sid, e) for sid, e in sessions.items() if e.get("dir")]
	return sorted(rendered, key=lambda kv: (kv[1].get("created_at") is None, kv[1].get("created_at") or "", kv[0]))


def rebuild_indexes(root: Path, registry: Any) -> int:
	"""Reconstruye índices por fuente y por mes. Devuelve cuántos ficheros escribió."""
	written = 0

	index_dir = root / "index"
	index_dir.mkdir(parents=True, exist_ok=True)
	by_month: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}

	for source, sessions in sorted(registry.state["registry"].items()):
		ordered = _sorted_sessions(sessions)
		if not ordered:
			continue
		lines = [f"# Índice — {source}", "", f"{len(ordered)} sesiones, cronológicas.", ""]
		lines += [_entry_line(sid, entry, "../") for sid, entry in ordered]
		(index_dir / f"{source}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
		written += 1
		for sid, entry in ordered:
			by_month.setdefault(entry["month"], []).append((sid, entry))

	for month, entries in sorted(by_month.items()):
		month_dir = root / month
		if not month_dir.is_dir():
			continue
		entries.sort(key=lambda kv: (kv[1].get("created_at") is None, kv[1].get("created_at") or "", kv[0]))
		lines = [f"# {month}", "", f"{len(entries)} sesiones este mes.", ""]
		lines += [_entry_line(sid, entry, "../") for sid, entry in entries]
		(month_dir / "_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
		written += 1

	return written
