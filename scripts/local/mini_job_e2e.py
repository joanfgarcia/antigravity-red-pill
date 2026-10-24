#!/usr/bin/env python3
"""E2E: two local-mini jobs through the Centralized Job Manager.

Forge fixes the seeded median bug; Loom (read-only tools) reviews the same
continuity. Both run through `agentic_job` + `AgenticJobDriver` + MiniLocalBridge.
The model servers are transient systemd --user units with cgroups.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from mini_services import start_forge, start_loom, stop_unit, tail, wait_http, wait_uds

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.paths import get_models_dir
from red_pill.core.queue_worker import process_driver_jobs
from red_pill.mini.providers import HTTPProvider, UnixHTTPProvider
from red_pill.mini.smoke import PHASE1_TASK, prepare_fixture
from red_pill.mini.tools import WorkspaceTools
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry

PHASE2_TOOLS_TASK = """Using the session history and the read-only tools:
1. State the RUN_ID from the first failing test output.
2. Quote the failing assertion.
3. Verify the current workspace by reading calc.py. test_calc.py may be
unavailable; if so, use the session history. Do not run commands and do not
modify files.
4. Judge whether the fix is correct and why.
5. Name one missing edge case (do not implement it).
Cite exact evidence."""


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--workspace", default="/tmp/red-pill-mini/e2e-ws")
	parser.add_argument("--gpu-socket", default="/tmp/red-pill-mini/e2e-forge.sock")
	parser.add_argument("--flm-url", default="http://127.0.0.1:52625")
	parser.add_argument("--forge-server", default=os.getenv("RED_PILL_FORGE_SERVER") or shutil.which("llama-server") or "")
	parser.add_argument("--forge-model", default=str(get_models_dir() / "Qwen3.5-9B-Q4_K_M.gguf"))
	parser.add_argument("--forge-memory", default="7G")
	parser.add_argument("--loom-memory", default="10G")
	parser.add_argument("--flm-bin", default="/usr/bin/flm")
	parser.add_argument("--loom-model", default="qwen3:8b")
	parser.add_argument("--keep", action="store_true")
	args = parser.parse_args()
	if not args.forge_server:
		print("[e2e] set --forge-server or RED_PILL_FORGE_SERVER", file=sys.stderr)
		return 4

	root = Path(args.workspace).parent
	root.mkdir(parents=True, exist_ok=True)
	Path(args.gpu_socket).parent.mkdir(parents=True, exist_ok=True)
	Path(args.gpu_socket).unlink(missing_ok=True)
	pid = os.getpid()
	forge_unit = f"red-pill-forge-e2e-{pid}"
	loom_unit = f"red-pill-loom-e2e-{pid}"
	forge_log = root / "forge-e2e.log"
	loom_log = root / "loom-e2e.log"
	try:
		start_forge(forge_unit, server=args.forge_server, model=args.forge_model, socket=args.gpu_socket, log=forge_log, memory=args.forge_memory)
		if not wait_uds(UnixHTTPProvider(args.gpu_socket), forge_unit, 180):
			print("[e2e] Forge unhealthy:\n" + tail(forge_log), file=sys.stderr)
			return 2
		start_loom(loom_unit, flm_bin=args.flm_bin, model=args.loom_model, log=loom_log, url=args.flm_url, memory=args.loom_memory)
		if not wait_http(HTTPProvider(args.flm_url), loom_unit, 240):
			print("[e2e] Loom unhealthy:\n" + tail(loom_log), file=sys.stderr)
			return 3

		fixture = prepare_fixture(args.workspace)
		run_id = fixture["run_id"]
		continuity = uuid.uuid4().hex[:12]
		mission = "mission:mini-job-e2e"
		session_db = str(root / "session.db")
		jobs = CognitiveQueueManager(str(root / "jobs.db"))
		base = {
			"backend": "local-mini",
			"continuity_id": continuity,
			"mission_id": mission,
			"workspace": args.workspace,
			"db_path": session_db,
			"gpu_socket": args.gpu_socket,
			"flm_url": args.flm_url,
			"timeout": 600,
		}
		forge_payload = {**base, "profile": "forge", "prompt": PHASE1_TASK, "title": "e2e-forge"}
		loom_payload = {**base, "profile": "loom-tools", "prompt": PHASE2_TOOLS_TASK, "title": "e2e-loom"}
		forge_job = jobs.enqueue_task("agentic_job", forge_payload, mission_id=mission)
		forge_processed = process_driver_jobs(jobs, max_jobs=1)
		forge_task = jobs.get_task(forge_job) or {}
		tests = WorkspaceTools(args.workspace).run_tests()
		# Loom must cite the RUN_ID from the mirror, not from a file it can read.
		(Path(args.workspace) / "test_calc.py").unlink(missing_ok=True)
		loom_job = jobs.enqueue_task("agentic_job", loom_payload, mission_id=mission)
		loom_processed = process_driver_jobs(jobs, max_jobs=1)
		processed = forge_processed + loom_processed
		loom_task = jobs.get_task(loom_job) or {}
		active = [row for row in SessionRegistry(session_db).get_by_continuity(continuity) if row.get("ttl_state") != "expired"]
		forge_response = str((forge_task.get("checkpoint_data") or {}).get("response") or "")
		loom_response = str((loom_task.get("checkpoint_data") or {}).get("response") or "")
		mirror_turns = SessionMirror(session_db).read_turns(continuity)
		forge_turns = [t for t in mirror_turns if str(t.get("originator") or "").startswith("forge:")]
		forge_cites_run_id = run_id in forge_response
		loom_saw_forge = any(run_id in str(t.get("content") or "") for t in forge_turns)
		ss_out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
		loom_loopback_only = "127.0.0.1:52625" in ss_out and "0.0.0.0:52625" not in ss_out
		forge_socket_ok = Path(args.gpu_socket).exists()
		report = {
			"processed": processed,
			"run_id": run_id,
			"forge_job": forge_job,
			"forge_status": forge_task.get("status"),
			"forge_response": forge_response[:1000],
			"loom_job": loom_job,
			"loom_status": loom_task.get("status"),
			"loom_response": loom_response[:1000],
			"tests_ok": tests.get("ok"),
			"forge_cites_run_id": forge_cites_run_id,
			"loom_cites_run_id": run_id in loom_response,
			"loom_saw_forge": loom_saw_forge,
			"loom_loopback_only": loom_loopback_only,
			"forge_socket_ok": forge_socket_ok,
			"mirror_turns": len(mirror_turns),
			"one_active_leg": len(active) == 1,
			"active_body": active[0]["originator"].split(":", 1)[0] if active else None,
		}
		print(json.dumps(report, ensure_ascii=False, indent=2))
		ok = bool(report["tests_ok"]) and report["forge_status"] == "COMPLETED" and report["loom_status"] == "COMPLETED" and report["forge_cites_run_id"] and report["loom_cites_run_id"] and report["loom_saw_forge"] and report["loom_loopback_only"] and report["forge_socket_ok"] and report["one_active_leg"]
		return 0 if ok else 1
	finally:
		if not args.keep:
			stop_unit(loom_unit)
			stop_unit(forge_unit)
			Path(args.gpu_socket).unlink(missing_ok=True)
		else:
			print(f"[e2e] keeping {forge_unit} {loom_unit}", file=sys.stderr)


if __name__ == "__main__":
	raise SystemExit(main())
