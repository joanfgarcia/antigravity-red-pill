#!/usr/bin/env python3
"""Run the Forge/Loom smoke with real local models, inside systemd cgroups.

Forge: CUDA `llama-server` on a Unix socket (Qwen3.5-9B Q4).
Loom: FLM on loopback (Qwen3-8B by default; the 35B does not fit with the IDE).

Both run as transient `systemd --user` units with `MemoryMax` and
`MemorySwapMax=0`, so a model that exceeds its budget dies alone instead of
taking the system down. Units are stopped on exit unless `--keep` is used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from mini_services import start_forge, start_loom, stop_unit, tail, wait_http, wait_uds

from red_pill.core.paths import get_models_dir
from red_pill.mini.providers import HTTPProvider, UnixHTTPProvider
from red_pill.mini.smoke import run_smoke


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--workspace", default="/tmp/red-pill-mini/ws")
	parser.add_argument("--gpu-socket", default="/tmp/red-pill-mini/forge.sock")
	parser.add_argument("--flm-url", default="http://127.0.0.1:52625")
	parser.add_argument("--forge-server", default=None, help="llama-server binary; default: RED_PILL_FORGE_SERVER or PATH")
	parser.add_argument("--forge-model", default=str(get_models_dir() / "Qwen3.5-9B-Q4_K_M.gguf"))
	parser.add_argument("--forge-memory", default="7G")
	parser.add_argument("--forge-ctx", type=int, default=4096)
	parser.add_argument("--flm-bin", default="/usr/bin/flm")
	parser.add_argument("--loom-model", default="qwen3:8b")
	parser.add_argument("--loom-memory", default="10G")
	parser.add_argument("--loom-ctx", type=int, default=4096)
	parser.add_argument("--keep", action="store_true")
	args = parser.parse_args()
	if not args.forge_server:
		args.forge_server = os.getenv("RED_PILL_FORGE_SERVER") or shutil.which("llama-server") or ""
	if not args.forge_server:
		print("[mini] set --forge-server or RED_PILL_FORGE_SERVER (llama-server not in PATH)", file=sys.stderr)
		return 4

	root = Path(args.workspace).parent
	root.mkdir(parents=True, exist_ok=True)
	Path(args.gpu_socket).parent.mkdir(parents=True, exist_ok=True)
	Path(args.gpu_socket).unlink(missing_ok=True)
	forge_log = root / "forge.log"
	loom_log = root / "loom.log"
	pid = os.getpid()
	forge_unit = f"red-pill-forge-smoke-{pid}"
	loom_unit = f"red-pill-loom-smoke-{pid}"
	try:
		print(f"[mini] starting Forge ({forge_unit}, MemoryMax={args.forge_memory})", flush=True)
		start_forge(forge_unit, server=args.forge_server, model=args.forge_model, socket=args.gpu_socket, log=forge_log, memory=args.forge_memory, ctx=args.forge_ctx)
		if not wait_uds(UnixHTTPProvider(args.gpu_socket), forge_unit, 180):
			print("[mini] Forge did not become healthy:\n" + tail(forge_log), file=sys.stderr)
			return 2

		print(f"[mini] starting Loom ({loom_unit}, MemoryMax={args.loom_memory})", flush=True)
		start_loom(loom_unit, flm_bin=args.flm_bin, model=args.loom_model, log=loom_log, url=args.flm_url, memory=args.loom_memory, ctx=args.loom_ctx)
		if not wait_http(HTTPProvider(args.flm_url), loom_unit, 240):
			print("[mini] Loom did not become healthy:\n" + tail(loom_log), file=sys.stderr)
			return 3

		report = run_smoke(
			args.workspace,
			forge_provider=UnixHTTPProvider(args.gpu_socket),
			loom_provider=HTTPProvider(args.flm_url),
			db_path=str(root / "session.db"),
		)
		print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
		return 0 if report.get("ok") else 1
	finally:
		if args.keep:
			print(f"[mini] keeping units: {forge_unit} {loom_unit}", file=sys.stderr)
		else:
			stop_unit(loom_unit)
			stop_unit(forge_unit)


if __name__ == "__main__":
	raise SystemExit(main())
