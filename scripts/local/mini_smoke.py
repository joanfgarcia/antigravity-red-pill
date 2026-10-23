#!/usr/bin/env python3
"""Run the Forge/Loom smoke with real local models, inside systemd cgroups.

Forge: CUDA `llama-server` on a Unix socket (Granite 8B).
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
import subprocess
import sys
import time
from pathlib import Path

from red_pill.core.paths import get_models_dir
from red_pill.mini.providers import HTTPProvider, UnixHTTPProvider
from red_pill.mini.smoke import run_smoke


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
	return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _stop_unit(unit: str) -> None:
	_run(["systemctl", "--user", "stop", unit])
	_run(["systemctl", "--user", "reset-failed", unit])


def _start_unit(unit: str, cmd: list[str], *, log: Path, memory: str) -> None:
	log.parent.mkdir(parents=True, exist_ok=True)
	log.touch()
	_stop_unit(unit)
	args = [
		"systemd-run",
		"--user",
		"--unit",
		unit,
		"--collect",
		"-p",
		f"MemoryMax={memory}",
		"-p",
		"MemorySwapMax=0",
		"-p",
		f"StandardOutput=append:{log}",
		"-p",
		f"StandardError=append:{log}",
		"--",
		*cmd,
	]
	result = _run(args)
	if result.returncode != 0:
		raise RuntimeError(f"systemd-run failed for {unit}: {result.stderr.strip() or result.stdout.strip()}")


def _unit_active(unit: str) -> bool:
	return _run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0


def _wait_uds(provider: UnixHTTPProvider, unit: str, seconds: int) -> bool:
	deadline = time.time() + seconds
	while time.time() < deadline:
		if provider.health():
			return True
		if not _unit_active(unit):
			return False
		time.sleep(1)
	return False


def _wait_http(provider: HTTPProvider, unit: str, seconds: int) -> bool:
	deadline = time.time() + seconds
	while time.time() < deadline:
		if provider.health():
			return True
		if not _unit_active(unit):
			return False
		time.sleep(2)
	return False


def _tail(path: Path, lines: int = 20) -> str:
	try:
		return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
	except OSError:
		return "(no log)"


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
		forge_cmd = [
			"/usr/bin/env",
			f"LD_LIBRARY_PATH={Path(args.forge_server).parent}",
			args.forge_server,
			"-m", args.forge_model,
			"--host", args.gpu_socket,
			"--ctx-size", str(args.forge_ctx),
			"--n-gpu-layers", "99",
			"--jinja",
			"--flash-attn", "on",
			"--no-webui",
		]
		print(f"[mini] starting Forge ({forge_unit}, MemoryMax={args.forge_memory})", flush=True)
		_start_unit(forge_unit, forge_cmd, log=forge_log, memory=args.forge_memory)
		if not _wait_uds(UnixHTTPProvider(args.gpu_socket), forge_unit, 180):
			print("[mini] Forge did not become healthy:\n" + _tail(forge_log), file=sys.stderr)
			return 2

		loom_cmd = [
			args.flm_bin, "serve", args.loom_model,
			"--host", "127.0.0.1", "--port", "52625",
			"--ctx-len", str(args.loom_ctx),
		]
		print(f"[mini] starting Loom ({loom_unit}, MemoryMax={args.loom_memory})", flush=True)
		_start_unit(loom_unit, loom_cmd, log=loom_log, memory=args.loom_memory)
		if not _wait_http(HTTPProvider(args.flm_url), loom_unit, 240):
			print("[mini] Loom did not become healthy:\n" + _tail(loom_log), file=sys.stderr)
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
			_stop_unit(loom_unit)
			_stop_unit(forge_unit)


if __name__ == "__main__":
	raise SystemExit(main())
