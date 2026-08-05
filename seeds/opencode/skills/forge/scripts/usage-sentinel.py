#!/usr/bin/env python3
# usage-sentinel.py — Forge — Background watch loop.
#
# OS-agnostic sentinel for the usage watch: Python stdlib ONLY
# (json/os/subprocess/time/datetime).
# Runs on Linux, macOS and Windows with the same contract.
#
# Contract with the harness:
#   · Each stdout line is an EVENT (the orchestrator polls the flag file).
#   · While there is nothing to say, it prints NOTHING → zero tokens.
#   · On firing it writes .swarm/STOP_REQUESTED.json, prints ONE line and ends
#     (one alarm, not a machine gun).
# Why a pure loop and not a subagent: a polling subagent spends tokens from the
# SAME pool it tries to protect (each poll is a model turn). This loop is pure
# Python: it watches for free. It dies with the session — no zombies.
#
# Usage (launched by the orchestrator when assembling a mission):
#   python3 <skill>/scripts/usage-sentinel.py <project_dir>
#   # Windows:   python  <skill>/scripts/usage-sentinel.py <project_dir>
#
# Options (CLI flags override env vars):
#   --threshold N   stop threshold in %  (default SWARM_SENTINEL_THRESHOLD or 93)
#   --interval S    seconds between polls (default SWARM_SENTINEL_INTERVAL or 300)

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import time


def emit(*parts: str) -> None:
    """One event per line, flushed immediately (the orchestrator may tail it)."""
    print(*parts, flush=True)


def utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_probe(probe_path: str, state_path: str, threshold: float) -> dict:
    """Run usage-probe.mjs (node) and parse its single JSON line. Fail-open."""
    try:
        r = subprocess.run(
            ["node", probe_path, state_path, "--threshold", str(threshold)],
            capture_output=True, text=True, timeout=60,
        )
        line = next((ln for ln in r.stdout.splitlines() if ln.strip().startswith("{")), None)
        if line:
            return json.loads(line)
    except Exception:
        pass
    return {}


def read_status(state_path: str) -> str:
    try:
        with open(state_path, encoding="utf-8") as f:
            return str((json.load(f).get("mission_status") or "UNKNOWN"))
    except Exception:
        return "UNKNOWN"


def read_spent(state_path: str) -> int:
    try:
        with open(state_path, encoding="utf-8") as f:
            ledger = json.load(f).get("usage_ledger") or {}
            return int(ledger.get("spent_tokens") or 0)
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Forge usage sentinel (os-agnostic, stdlib only).")
    parser.add_argument("project_dir", help="absolute path to the mission workspace")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--interval", type=int, default=None)
    args = parser.parse_args()

    threshold = args.threshold if args.threshold is not None else float(os.environ.get("SWARM_SENTINEL_THRESHOLD", "93"))
    interval = args.interval if args.interval is not None else int(os.environ.get("SWARM_SENTINEL_INTERVAL", "300"))

    project_dir = os.path.abspath(args.project_dir)
    state_path = os.path.join(project_dir, ".swarm", "state.json")
    flag_path = os.path.join(project_dir, ".swarm", "STOP_REQUESTED.json")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    probe_path = os.path.join(skill_dir, "usage-probe.mjs")

    # The flag file is single-use: a leftover from a previous pause that was
    # already reconciled must not fire a phantom stop.
    try:
        os.remove(flag_path)
    except OSError:
        pass

    while True:
        if not os.path.isfile(state_path):
            emit(f"SENTINEL-END no state.json in {project_dir} — sentinel retires")
            return 0

        reading = read_probe(probe_path, state_path, threshold)
        util = reading.get("max_utilization")
        util = float(util) if isinstance(util, (int, float)) else 0.0
        resets = reading.get("window_reset_at")
        spent = read_spent(state_path)
        status = read_status(state_path)

        # The mission is no longer alive: the sentinel retires by itself
        # (zero zombies).
        if status != "RUNNING":
            emit(f"SENTINEL-END mission in state {status} — sentinel no longer needed, retiring")
            return 0

        # Fire: threshold reached.
        if util >= threshold:
            payload = {
                "requested_at": utcnow_iso(),
                "reason": f"usage at {util}% (threshold {threshold}%)",
                "utilization": util,
                "threshold": threshold,
                "source": "usage-probe.mjs",
                "spent_tokens": spent,
                "window_reset_at": resets,
                "instruction": (
                    "Execute the controlled stop of controlled-stop.md §3 with "
                    "mission_status=PAUSED_USAGE_LIMIT, schedule the resume "
                    "(usage-sentinel.md §4) and present the prompt in the chat."
                ),
            }
            with open(flag_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            emit(
                f"SENTINEL-STOP usage at {util}% (threshold {threshold}%, {spent} tokens spent). "
                f"CONTROLLED STOP NOW: controlled-stop.md §3. Window reset: {resets}. "
                f"Flag in .swarm/STOP_REQUESTED.json"
            )
            return 0

        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
