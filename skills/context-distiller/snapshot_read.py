#!/usr/bin/env python3
"""Read-mark ledger for the context-distiller snapshot (v3).

The snapshot (`session_snapshot.md`) is the workspace cold-start handoff. This
ledger answers one question cheaply — *was this exact snapshot version already
consumed by this session?* — without reading the snapshot body and without
rewriting it.

Layout (next to the snapshot):

	<workspace>/.red-pill/memory/session_snapshot.md
	<workspace>/.red-pill/memory/session_snapshot.reads.jsonl

The JSONL is append-only: one line per check/mark, small and atomic. The
`snapshot_sha` pins the version, so any edit to the snapshot invalidates the
previous reads. A verdict of `SKIP_CANDIDATE` is advisory: skip only if the
snapshot is still in your hot context; after compaction, read it again.

Usage:
	python3 snapshot_read.py check --originator opencode:ses_x [--continuity-id C]
	python3 snapshot_read.py mark  --originator opencode:ses_x --action read
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TAIL = 20


def snapshot_paths(workspace: str) -> tuple[Path, Path]:
	memory = Path(workspace).expanduser().resolve() / ".red-pill" / "memory"
	return memory / "session_snapshot.md", memory / "session_snapshot.reads.jsonl"


def sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as fh:
		for chunk in iter(lambda: fh.read(65536), b""):
			digest.update(chunk)
	return digest.hexdigest()


def tail_entries(path: Path, limit: int) -> list[dict]:
	try:
		lines = path.read_text(encoding="utf-8").splitlines()
	except FileNotFoundError:
		return []
	entries: list[dict] = []
	for line in lines[-limit:]:
		line = line.strip()
		if not line:
			continue
		try:
			entry = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(entry, dict):
			entries.append(entry)
	return entries


def cmd_check(args: argparse.Namespace) -> int:
	snapshot, ledger = snapshot_paths(args.workspace)
	if not snapshot.exists():
		print(json.dumps({"verdict": "MISSING", "snapshot": str(snapshot)}))
		return 0

	digest = sha256(snapshot)
	entries = tail_entries(ledger, args.tail)
	same_version = [e for e in entries if e.get("snapshot_sha") == digest]
	mine = [
		e
		for e in same_version
		if e.get("originator") == args.originator and e.get("action") == "read"
	]
	print(
		json.dumps(
			{
				"verdict": "SKIP_CANDIDATE" if mine else "READ",
				"snapshot": str(snapshot),
				"snapshot_sha": digest,
				"same_version_entries": len(same_version),
				"same_originator_read": mine[-1] if mine else None,
				"last_entry": entries[-1] if entries else None,
			},
			ensure_ascii=False,
		)
	)
	return 0


def cmd_mark(args: argparse.Namespace) -> int:
	snapshot, ledger = snapshot_paths(args.workspace)
	if not snapshot.exists():
		print(json.dumps({"error": "snapshot_missing", "snapshot": str(snapshot)}))
		return 2

	entry = {
		"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
		"originator": args.originator or "",
		"continuity_id": args.continuity_id or "",
		"session_id": args.session_id or "",
		"snapshot_sha": sha256(snapshot),
		"action": args.action,
	}
	line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
	ledger.parent.mkdir(parents=True, exist_ok=True)
	fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o664)
	try:
		os.write(fd, line.encode("utf-8"))
	finally:
		os.close(fd)
	print(line.rstrip("\n"))
	return 0


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Snapshot read-mark ledger (v3)")
	parser.add_argument("--workspace", default=os.getcwd(), help="workspace root (default: cwd)")
	sub = parser.add_subparsers(dest="command", required=True)

	check = sub.add_parser("check", help="decide whether to read the snapshot body")
	check.add_argument("--originator", required=True, help="provider:session id of this body")
	check.add_argument("--continuity-id", default="", help="soul id (informational)")
	check.add_argument("--tail", type=int, default=DEFAULT_TAIL, help="ledger lines to inspect")
	check.set_defaults(func=cmd_check)

	mark = sub.add_parser("mark", help="append a read mark to the ledger")
	mark.add_argument("--originator", required=True, help="provider:session id of this body")
	mark.add_argument("--continuity-id", default="", help="soul id (informational)")
	mark.add_argument("--session-id", default="", help="native harness session id")
	mark.add_argument("--action", choices=("read", "skipped"), default="read")
	mark.set_defaults(func=cmd_mark)
	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	return args.func(args)


if __name__ == "__main__":
	sys.exit(main())
