"""Read-mark ledger del context-distiller (v3).

El ledger es un JSONL append-only junto al snapshot. `check` decide si hay que
leer el cuerpo (hash + cola del ledger, sin leer el snapshot) y `mark` apunta la
decisión. Estos tests fijan el contrato mínimo: fail-open, versión por sha,
lector por originator.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "context-distiller" / "snapshot_read.py"

SNAPSHOT = "---\ntype: log\nstatus: active\n---\n\n# Frontera\n"


def _run(ws: Path, *args: str) -> dict:
	res = subprocess.run(
		[sys.executable, str(SCRIPT), "--workspace", str(ws), *args],
		capture_output=True,
		text=True,
		check=True,
	)
	return json.loads(res.stdout)


def test_missing_snapshot(tmp_path):
	assert _run(tmp_path, "check", "--originator", "opencode:s1")["verdict"] == "MISSING"


def test_unread_then_skip_candidate(tmp_path):
	(tmp_path / ".red-pill" / "memory").mkdir(parents=True)
	(tmp_path / ".red-pill" / "memory" / "session_snapshot.md").write_text(SNAPSHOT, encoding="utf-8")

	assert _run(tmp_path, "check", "--originator", "opencode:s1")["verdict"] == "READ"
	_run(tmp_path, "mark", "--originator", "opencode:s1", "--action", "read")
	assert _run(tmp_path, "check", "--originator", "opencode:s1")["verdict"] == "SKIP_CANDIDATE"


def test_other_originator_must_read(tmp_path):
	(tmp_path / ".red-pill" / "memory").mkdir(parents=True)
	(tmp_path / ".red-pill" / "memory" / "session_snapshot.md").write_text(SNAPSHOT, encoding="utf-8")
	_run(tmp_path, "mark", "--originator", "opencode:s1")

	assert _run(tmp_path, "check", "--originator", "opencode:s2")["verdict"] == "READ"


def test_snapshot_edit_invalidates_reads(tmp_path):
	memory = tmp_path / ".red-pill" / "memory"
	memory.mkdir(parents=True)
	(memory / "session_snapshot.md").write_text(SNAPSHOT, encoding="utf-8")
	_run(tmp_path, "mark", "--originator", "opencode:s1")

	(memory / "session_snapshot.md").write_text(SNAPSHOT + "\n## 1. Frontera actual\n- nuevo\n", encoding="utf-8")
	assert _run(tmp_path, "check", "--originator", "opencode:s1")["verdict"] == "READ"
