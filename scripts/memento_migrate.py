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
	enabled += list(getattr(cfg, "MEMENTO_EXTRA_SOURCES", []))
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


def _orphan_sessions(registry: Any) -> List[Tuple[str, str]]:
	"""[(source, session_id)] presentes en archive_memories pero en ningún provider store ni en el registry.

	Prioridad de fuentes §5.1: los stores mandan; esto rescata SOLO lo que ya no
	retiene ningún IDE. La fuente se infiere del prefijo del session_id
	(antigravity acuñó los suyos sin prefijo, ver ChronicleSourcePlugin.session_prefix).
	"""
	known = {session_id for sessions in registry.state["registry"].values() for session_id in sessions}
	try:
		from red_pill.memory import MemoryManager

		mem = MemoryManager()
		session_ids, offset = set(), None
		while True:
			batch, offset = mem.client.scroll("archive_memories", limit=1000, with_payload=["session_id", "type"], offset=offset)
			for point in batch:
				payload = point.payload or {}
				if payload.get("session_id") and payload.get("type") != "idea_fragment":
					session_ids.add(str(payload["session_id"]))
			if offset is None:
				break
	except Exception as e:
		logger.error(f"archive_memories unavailable for orphan discovery: {e}")
		return []

	orphans = []
	for session_id in sorted(session_ids - known):
		source = session_id.split(":", 1)[0] if ":" in session_id else "antigravity"
		orphans.append((source, session_id))
	return orphans


def _export_raw(plugin: Any, cid: str, session_id: str, step_count: Optional[int], workspace: Optional[str], session_dir: Path, now: str) -> None:
	"""Escribe `raw/raw.*` + `raw/meta.json`: la copia de respaldo autocontenida (§4.2)."""
	import json as _json

	try:
		raw_dir = session_dir / "raw"
		raw_dir.mkdir(parents=True, exist_ok=True)
		raw_path = plugin.export_raw(cid, raw_dir)
		if raw_path is None:
			return
		meta = {"session_id": session_id, "source": plugin.name, "conversation_id": cid, "step_count": step_count, "workspace": workspace, "exported_at": now}
		(raw_dir / "meta.json").write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
	except Exception as e:
		logger.warning(f"[{plugin.name}] raw export failed for {cid}: {e}")


def _raw_file_of(raw_dir: Path) -> Optional[Path]:
	return next((f for f in sorted(raw_dir.glob("raw.*")) if f.name != "raw.meta"), None)


def _load_from_raw(root: Path, registry: Any, plugin: Any, session_id: str) -> Optional[List[Dict[str, Any]]]:
	"""Renormaliza desde la copia raw/ existente de una sesión ya renderizada antes."""
	entry = registry.get(plugin.name, session_id) or {}
	if not entry.get("dir"):
		return None
	raw_dir = root / entry["dir"] / "raw"
	raw_file = _raw_file_of(raw_dir) if raw_dir.is_dir() else None
	if raw_file is None:
		return None
	try:
		return plugin.load_raw(raw_file) or None
	except Exception as e:
		logger.warning(f"[{plugin.name}] raw reload failed for {session_id}: {e}")
		return None


def _regenerate_from_raw(root: Path, registry: Any, split_max_messages: int, split_max_chars: int, now: str) -> Tuple[int, int]:
	"""Regenera el árbol entero desde las copias raw/ (el respaldo ES la fuente). → (rendered, failed)."""
	import json as _json

	from red_pill.chronicle_sources.base import discover_source_plugins
	from red_pill.memento.registry import recompute_chain
	from red_pill.memento.render import render_session, write_session

	plugins = {p.name: p for p in discover_source_plugins(only_enabled=False)}
	rendered_count, failed = 0, 0
	touched_sources = set()
	for meta_file in sorted(root.glob("*/*/*/raw/meta.json")):
		try:
			meta = _json.loads(meta_file.read_text(encoding="utf-8"))
			plugin = plugins.get(meta.get("source", ""))
			raw_file = _raw_file_of(meta_file.parent)
			if plugin is None or raw_file is None:
				failed += 1
				continue
			messages = plugin.load_raw(raw_file)
			if not messages:
				failed += 1
				continue
			session_id = meta["session_id"]
			entry = registry.get(plugin.name, session_id) or {}
			month = entry.get("month") or meta_file.parents[3].name  # inmutabilidad §4.3: el path manda
			rendered = render_session(
				session_id,
				plugin.name,
				plugin.name,
				messages,
				workspace=meta.get("workspace"),
				prev_session=entry.get("prev_session"),
				next_session=entry.get("next_session"),
				step_count=meta.get("step_count"),
				split_max_messages=split_max_messages,
				split_max_chars=split_max_chars,
				month_override=month,
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
					"step_count": meta.get("step_count"),
					"body_chars": rendered.body_chars,
					"has_splits": rendered.has_splits,
					"memento_hash": rendered.memento_hash,
					"reconstructed": False,
				},
			)
			touched_sources.add(plugin.name)
			rendered_count += 1
		except Exception as e:
			logger.warning(f"from-raw regeneration failed for {meta_file.parent.parent}: {e}")
			failed += 1

	for source in sorted(touched_sources):
		recompute_chain(root, registry, source)
	return rendered_count, failed


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
	for max_messages, max_chars in [(30, 8000), (200, 12000), (30, 24000), (50, 48000), (100, 96000), (200, 192000)]:
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
	parser.add_argument(
		"--reconstruct-orphans",
		action="store_true",
		help="Render sessions that exist only in archive_memories (no provider store retains them) as reconstructed: true (§5.1.2)",
	)
	parser.add_argument(
		"--from-raw",
		action="store_true",
		help="Regenerate the whole tree from the raw/ backup copies (no provider stores needed) and exit",
	)
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry, recompute_chain
	from red_pill.memento.render import render_session, write_session

	registry = MementoRegistry()
	if args.cata:
		print(_cata(registry))
		return

	if args.from_raw:
		root = get_memento_root()
		now = datetime.now(timezone.utc).isoformat()
		rendered_count, failed = _regenerate_from_raw(
			root, registry, int(getattr(cfg, "MEMENTO_SPLIT_MAX_MESSAGES", 30)), int(getattr(cfg, "MEMENTO_SPLIT_MAX_CHARS", 24000)), now
		)
		from red_pill.memento.indexes import rebuild_indexes

		rebuild_indexes(root, registry)
		registry.save()
		logger.info(f"From-raw regeneration complete: {rendered_count} session(s) rendered, {failed} failed.")
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

	if not pending and not args.reconstruct_orphans:
		registry.save()
		return

	split_max_messages = int(getattr(cfg, "MEMENTO_SPLIT_MAX_MESSAGES", 30))
	split_max_chars = int(getattr(cfg, "MEMENTO_SPLIT_MAX_CHARS", 24000))
	raw_enabled = bool(getattr(cfg, "MEMENTO_RAW_ENABLED", True))
	now = datetime.now(timezone.utc).isoformat()
	rendered_count, skipped = 0, 0
	touched_sources = set()

	for plugin, cid, session_id, step_count in pending:
		reconstructed = False
		try:
			messages = plugin.load(cid)
		except Exception as e:
			# Prioridad §5.1: store vivo > raw/ (verbatim) > archive_memories (refinado)
			messages = _load_from_raw(root, registry, plugin, session_id)
			if messages is None:
				logger.warning(f"[{plugin.name}] load({cid}) failed ({e}); attempting reconstruction from archive_memories.")
				messages = _reconstruct(session_id)
				reconstructed = messages is not None
			else:
				logger.info(f"[{plugin.name}] load({cid}) failed; re-rendered from raw/ backup.")

		if not messages:
			# Sin mensajes útiles también se registra (sin dir): no reintentar cada noche
			registry.upsert(plugin.name, session_id, {"step_count": step_count, "rendered_at": now})
			skipped += 1
			continue

		entry = registry.get(plugin.name, session_id) or {}
		workspace = plugin.workspace_of(cid)
		rendered = render_session(
			session_id,
			plugin.name,
			plugin.name,
			messages,
			workspace=workspace,
			prev_session=entry.get("prev_session"),
			next_session=entry.get("next_session"),
			reconstructed=reconstructed,
			step_count=step_count,
			split_max_messages=split_max_messages,
			split_max_chars=split_max_chars,
			month_override=entry.get("month"),
		)
		session_dir = write_session(root, rendered)
		if raw_enabled and not reconstructed:
			_export_raw(plugin, cid, session_id, step_count, workspace, session_dir, now)
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

	if args.reconstruct_orphans:
		orphans = _orphan_sessions(registry)
		logger.info(f"Orphan sessions in archive_memories without provider store: {len(orphans)}")
		for source, session_id in orphans:
			messages = _reconstruct(session_id)
			if not messages:
				registry.upsert(source, session_id, {"rendered_at": now, "reconstructed": True})
				skipped += 1
				continue
			rendered = render_session(
				session_id,
				source,
				source,
				messages,
				reconstructed=True,
				split_max_messages=split_max_messages,
				split_max_chars=split_max_chars,
				month_override=(registry.get(source, session_id) or {}).get("month"),
			)
			write_session(root, rendered)
			registry.upsert(
				source,
				session_id,
				{
					"dir": rendered.dir_rel,
					"month": rendered.month,
					"created_at": rendered.created_at,
					"rendered_at": now,
					"message_count": rendered.message_count,
					"body_chars": rendered.body_chars,
					"has_splits": rendered.has_splits,
					"memento_hash": rendered.memento_hash,
					"reconstructed": True,
				},
			)
			touched_sources.add(source)
			rendered_count += 1

	for source in sorted(touched_sources):
		updated = recompute_chain(root, registry, source)
		if updated:
			logger.info(f"[{source}] Thread chain updated on {updated} session(s).")

	if touched_sources:
		from red_pill.memento.indexes import rebuild_indexes

		logger.info(f"Rebuilt {rebuild_indexes(root, registry)} index file(s).")

	registry.save()
	logger.info(f"Memento render complete: {rendered_count} session(s) rendered, {skipped} empty/failed.")


if __name__ == "__main__":
	main()
