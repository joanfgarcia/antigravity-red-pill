#!/usr/bin/env python3
"""One-off rescue: move captured turns that never became memories into the queue.

For a month, four capture surfaces (the opencode plugin, the Claude Code Stop
hook, the opencode bridge and the Antigravity worker) wrote every turn into a
private `interactions` table in bunker.db that no consumer ever read. The
janitor then swept rows older than 30 days into `universal_history.jsonl` and
deleted them. Capture worked; ingestion never existed.

This script recovers both pools — the live table and the archived JSONL — into
`memory_queue`, where the worker will ingest them into `interaction_memories`
like any other turn. The sink deduplicates by content hash, so running it twice
is harmless.

	python scripts/migrate_interactions_to_queue.py            # dry run
	python scripts/migrate_interactions_to_queue.py --apply
	python scripts/migrate_interactions_to_queue.py --apply --drop-table
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from red_pill.core.paths import get_aleth_core_root, get_db_dir  # noqa: E402
from red_pill.core.queue_manager import MemoryQueueManager  # noqa: E402

ORIGINATOR = "legacy_interactions"


def _rows_from_sqlite(db_path: Path):
	if not db_path.exists():
		return []
	conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
	try:
		if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'").fetchone():
			return []
		return [
			{"prompt": r[0] or "", "response": r[1] or "", "model": r[3], "when": r[2]}
			for r in conn.execute("SELECT user_prompt, agent_response, timestamp, model FROM interactions ORDER BY timestamp ASC")
		]
	finally:
		conn.close()


def _rows_from_jsonl(path: Path):
	if not path.exists():
		return []
	rows = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			item = json.loads(line)
		except json.JSONDecodeError:
			continue
		rows.append(
			{
				"prompt": item.get("user_prompt") or "",
				"response": item.get("agent_response") or "",
				"model": item.get("model"),
				"when": item.get("timestamp"),
			}
		)
	return rows


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--apply", action="store_true", help="Actually enqueue (default is a dry run)")
	parser.add_argument("--drop-table", action="store_true", help="Drop the interactions table once its rows are queued")
	args = parser.parse_args()

	db_path = get_db_dir() / "bunker.db"
	archive = get_aleth_core_root() / "history" / "universal_history.jsonl"

	live = _rows_from_sqlite(db_path)
	archived = _rows_from_jsonl(archive)
	print(f"interactions (bunker.db)      : {len(live)} turnos")
	print(f"universal_history.jsonl       : {len(archived)} turnos ya barridos")

	candidates = [r for r in live + archived if (r["prompt"].strip() or r["response"].strip())]
	print(f"con contenido                 : {len(candidates)}")

	if not args.apply:
		print("\n(dry run — vuelve a lanzarlo con --apply para encolarlos)")
		return 0

	queue = MemoryQueueManager()

	def _count() -> int:
		with sqlite3.connect(queue.db_path) as conn:
			return int(conn.execute("SELECT COUNT(*) FROM memory_queue").fetchone()[0])

	before = _count()
	for row in candidates:
		queue.enqueue_memory(
			prompt=row["prompt"],
			response=row["response"],
			role="assistant",
			originator=ORIGINATOR,
			model=row["model"],
			# These turns are weeks old; dedup has to look at the whole history,
			# not a recent window, so re-running the rescue stays harmless.
			dedup_window_hours=None,
		)
	queued = _count() - before

	print(f"\nencolados: {queued} nuevos | {len(candidates) - queued} ya estaban (deduplicados por contenido)")

	if args.drop_table and db_path.exists():
		conn = sqlite3.connect(str(db_path))
		try:
			conn.execute("DROP TABLE IF EXISTS interactions")
			conn.commit()
			print("tabla `interactions` eliminada: ya no hay un segundo sumidero.")
		finally:
			conn.close()

	print("El worker los ingerirá en la próxima pasada (`red-pill job process-queue` o el timer).")
	return 0


if __name__ == "__main__":
	sys.exit(main())
