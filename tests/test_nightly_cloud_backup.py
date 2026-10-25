"""Wrapper nocturno: encola el backup como hijo del job de sueño."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "scripts" / "nightly_cloud_backup.sh"


def test_wrapper_encola_backup_con_parent(tmp_path):
	calls = tmp_path / "calls"
	stub = tmp_path / "red-pill"
	stub.write_text(
		"#!/usr/bin/env bash\n"
		'echo "$@" >> "$CALLS"\n'
		'echo "[OK] Job 12345678-1234-1234-1234-123456789012 encolado (source=dag_job, priority=8)."\n',
		encoding="utf-8",
	)
	stub.chmod(0o755)
	env = {**os.environ, "RED_PILL_BIN": str(stub), "CALLS": str(calls)}
	res = subprocess.run(["bash", str(WRAPPER)], cwd=str(REPO), env=env, capture_output=True, text=True)
	assert res.returncode == 0, res.stderr
	lines = calls.read_text(encoding="utf-8").splitlines()
	assert len(lines) == 2
	assert "configs/jobs/nightly.yaml" in lines[0]
	assert "--recipe .red-pill/jobs/cloud_backup.yaml" in lines[1]
	assert "--parent 12345678" in lines[1]
	assert "--singleton" in lines[1]
