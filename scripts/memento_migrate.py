#!/usr/bin/env python3
"""
memento_migrate.py — Memento Chronicle backfill & delta render (RFC-002 §5.4, Fase 1).

Recorre los ChronicleSourcePlugin habilitados y vuelca cada sesión al árbol
Memento (`<memento>/<AAAA-MM>/<source>/<session>/memento/index.md`). Delta por
defecto (espejo del registry propio); `--all` fuerza el reproceso completo.
Si un provider store no responde, reconstruye desde `archive_memories`
(`reconstructed: true`). La pasada agéntica (distill/refine) NO vive aquí
(Fase 3.5); Qdrant no se toca jamás en modo escritura.

Usage:
	uv run python scripts/memento_migrate.py              # delta (lo que corre la noche)
	uv run python scripts/memento_migrate.py --all        # backfill histórico completo
	uv run python scripts/memento_migrate.py --dry-run    # censo, sin escribir (incluye memory_queue)
	uv run python scripts/memento_migrate.py --cata       # informe de calibración Q8 (markdown a stdout)
"""

import argparse
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_migrate")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _enabled_plugins(only: List[str]) -> List[Any]:
	import red_pill.config as cfg
	from red_pill.chronicle_sources.base import discover_source_plugins

	enabled = list(getattr(cfg, "MEMENTO_SOURCES", []) or []) or list(getattr(cfg, "CHRONICLE_ARCHIVE_SOURCES", []))
	plugins = [p for p in discover_source_plugins(only_enabled=False) if p.name in enabled]
	if only:
		plugins = [p for p in plugins if p.name in only]
	plugins.sort(key=lambda p: p.name)
	return plugins


def _find_pending(registry: Any, plugins: List[Any], force_all: bool) -> List[Tuple[Any, str, str, int]]:
	"""[(plugin, conversation_id, qualified_session_id, step_count)] pendientes de render."""
	pending = []
	for plugin in plugins:
		try:
			discovered = plugin.discover()
		except Exception as e:
			logger.error(f"Source '{plugin.name}' discovery failed: {e}")
			continue
		known = registry.sessions_of(plugin.name)
		for cid, step_count in discovered:
			session_id = plugin.qualify(cid)
			entry = known.get(session_id)
			if force_all or entry is None or step_count > int(entry.get("step_count") or -1):
				pending.append((plugin, cid, session_id, step_count))
	return pending


def _queue_census() -> Dict[str, int]:
	"""Filas de memory_queue por originator — expone superficies sin fuente (§5.4.5 / MUST 10)."""
	try:
		from red_pill.core.paths import get_queue_dir

		db = get_queue_dir() / "bunker_queue.db"
		if not db.exists():
			return {}
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		try:
			rows = con.execute("SELECT COALESCE(originator, '(null)'), COUNT(*) FROM memory_queue GROUP BY 1").fetchall()
		finally:
			con.close()
		return {str(originator): int(count) for originator, count in rows}
	except Exception as e:
		logger.debug(f"memory_queue census unavailable: {e}")
		return {}


def _reconstruct(session_id: str) -> Optional[List[Dict[str, Any]]]:
	"""Fallback §5.1.2: reconstruye la sesión desde archive_memories (texto refinado, no verbatim)."""
	try:
		from qdrant_client.http import models

		from red_pill.memory import MemoryManager

		mem = MemoryManager()
		session_filter = models.Filter(
			must=[models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))],
			must_not=[models.FieldCondition(key="type", match=models.MatchValue(value="idea_fragment"))],
		)
		points, offset = [], None
		while True:
			batch, offset = mem.client.scroll("archive_memories", scroll_filter=session_filter, limit=256, with_payload=True, offset=offset)
			points.extend(batch)
			if offset is None:
				break
		if not points:
			return None
		points.sort(key=lambda p: int((p.payload or {}).get("sequence_index") or 0))
		messages = []
		for point in points:
			payload = point.payload or {}
			content = payload.get("raw_content") or payload.get("refined_content") or ""
			if not str(content).strip():
				continue
			messages.append({"role": payload.get("role"), "content": content, "timestamp": payload.get("created_at")})
		return messages or None
	except Exception as e:
		logger.warning(f"Reconstruction from archive_memories failed for {session_id}: {e}")
		return None


def _percentiles(values: List[int]) -> str:
	if not values:
		return "—"
	ordered = sorted(values)

	def pct(q: float) -> int:
		return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

	return f"{pct(0.50)} / {pct(0.90)} / {pct(0.99)} / {ordered[-1]}"


def _cata(registry: Any) -> str:
	"""Informe de calibración Q8: distribución del corpus + simulación de umbrales de split."""
	rows: List[Tuple[str, int, int]] = []  # (source, message_count, body_chars)
	for source, sessions in registry.state["registry"].items():
		for entry in sessions.values():
			if entry.get("dir"):
				rows.append((source, int(entry.get("message_count") or 0), int(entry.get("body_chars") or 0)))
	if not rows:
		return "# Cata Memento — sin corpus\n\nEl registry está vacío: ejecuta primero el backfill (`--all`).\n"

	lines = [f"# Cata Memento — calibración Q8 ({datetime.now(timezone.utc).date().isoformat()})", ""]
	lines += ["## Corpus", "", "| source | sesiones | mensajes p50/p90/p99/max | chars p50/p90/p99/max |", "|---|---|---|---|"]
	for source in sorted({source for source, _m, _c in rows}) + ["TOTAL"]:
		subset = rows if source == "TOTAL" else [r for r in rows if r[0] == source]
		lines.append(f"| {source} | {len(subset)} | {_percentiles([m for _s, m, _c in subset])} | {_percentiles([c for _s, _m, c in subset])} |")

	lines += ["", "## Simulación de umbrales de split (mensajes / chars)", "", "| umbral | sesiones con split | % |", "|---|---|---|"]
	for max_messages, max_chars in [(30, 8000), (30, 24000), (50, 48000), (100, 96000), (200, 192000)]:
		hits = sum(1 for _s, messages, chars in rows if messages > max_messages or chars > max_chars)
		lines.append(f"| >{max_messages} msgs o >{max_chars} chars | {hits} | {hits * 100 // len(rows)}% |")

	lines += [
		"",
		"## Nota Q4",
		"",
		"La cata aporta la distribución de tamaños; el umbral de *significance* (Q4) necesita",
		"además el shadow-gate de la Fase 3.5 — no es decidible solo con volumetría.",
		"",
	]
	return "\n".join(lines)


def main() -> None:
	parser = argparse.ArgumentParser(description="Memento Chronicle backfill & delta render (RFC-002)")
	parser.add_argument("--all", action="store_true", help="Force full reprocess of every session of every enabled source")
	parser.add_argument("--dry-run", action="store_true", help="Report pending work and memory_queue census without writing")
	parser.add_argument("--source", action="append", default=[], help="Limit to a specific source (repeatable)")
	parser.add_argument("--cata", action="store_true", help="Print the Q8 calibration report (markdown) and exit")
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry, recompute_chain
	from red_pill.memento.render import render_session, write_session

	registry = MementoRegistry()
	if args.cata:
		print(_cata(registry))
		return

	plugins = _enabled_plugins(args.source)
	if not plugins:
		logger.error("No Memento sources enabled (MEMENTO_SOURCES / CHRONICLE_ARCHIVE_SOURCES). Nothing to do.")
		return

	root = get_memento_root()
	pending = _find_pending(registry, plugins, force_all=args.all)
	per_source = Counter(plugin.name for plugin, _cid, _sid, _steps in pending)
	summary = ", ".join(f"{name}={count}" for name, count in sorted(per_source.items())) or "nada pendiente"
	logger.info(f"Memento root: {root} — pending: {summary}")

	if args.dry_run:
		census = _queue_census()
		if census:
			known = {plugin.name for plugin in plugins}
			logger.info("memory_queue census (originator → rows):")
			for originator, count in sorted(census.items(), key=lambda kv: -kv[1]):
				covered = any(name in originator.lower() for name in known)
				logger.info(f"  {originator}: {count}{'' if covered else '  ← sin fuente Memento (MUST 10)'}")
		logger.info("[DRY RUN] No changes made.")
		return

	if not pending:
		registry.save()
		return

	split_max_messages = int(getattr(cfg, "MEMENTO_SPLIT_MAX_MESSAGES", 30))
	split_max_chars = int(getattr(cfg, "MEMENTO_SPLIT_MAX_CHARS", 24000))
	now = datetime.now(timezone.utc).isoformat()
	rendered_count, skipped = 0, 0
	touched_sources = set()

	for plugin, cid, session_id, step_count in pending:
		reconstructed = False
		try:
			messages = plugin.load(cid)
		except Exception as e:
			logger.warning(f"[{plugin.name}] load({cid}) failed ({e}); attempting reconstruction from archive_memories.")
			messages = _reconstruct(session_id)
			reconstructed = messages is not None

		if not messages:
			# Sin mensajes útiles también se registra (sin dir): no reintentar cada noche
			registry.upsert(plugin.name, session_id, {"step_count": step_count, "rendered_at": now})
			skipped += 1
			continue

		entry = registry.get(plugin.name, session_id) or {}
		rendered = render_session(
			session_id,
			plugin.name,
			plugin.name,
			messages,
			workspace=plugin.workspace_of(cid),
			prev_session=entry.get("prev_session"),
			next_session=entry.get("next_session"),
			reconstructed=reconstructed,
			step_count=step_count,
			split_max_messages=split_max_messages,
			split_max_chars=split_max_chars,
			month_override=entry.get("month"),
		)
		write_session(root, rendered)
		registry.upsert(
			plugin.name,
			session_id,
			{
				"dir": rendered.dir_rel,
				"month": rendered.month,
				"created_at": rendered.created_at,
				"rendered_at": now,
				"message_count": rendered.message_count,
				"step_count": step_count,
				"body_chars": rendered.body_chars,
				"has_splits": rendered.has_splits,
				"memento_hash": rendered.memento_hash,
				"reconstructed": reconstructed,
			},
		)
		touched_sources.add(plugin.name)
		rendered_count += 1

	for source in sorted(touched_sources):
		updated = recompute_chain(root, registry, source)
		if updated:
			logger.info(f"[{source}] Thread chain updated on {updated} session(s).")

	registry.save()
	logger.info(f"Memento render complete: {rendered_count} session(s) rendered, {skipped} empty/failed.")


if __name__ == "__main__":
	main()
