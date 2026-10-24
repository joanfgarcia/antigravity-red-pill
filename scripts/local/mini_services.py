"""Start/stop Forge/Loom as transient systemd --user units with cgroups.

Shared by the smoke and the job E2E scripts. No permanent services are created.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from red_pill.mini.providers import HTTPProvider, UnixHTTPProvider


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
	return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def stop_unit(unit: str) -> None:
	_run(["systemctl", "--user", "stop", unit])
	_run(["systemctl", "--user", "reset-failed", unit])


def start_unit(unit: str, cmd: list[str], *, log: Path, memory: str) -> None:
	log.parent.mkdir(parents=True, exist_ok=True)
	log.touch()
	stop_unit(unit)
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


def unit_active(unit: str) -> bool:
	return _run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0


def wait_uds(provider: UnixHTTPProvider, unit: str, seconds: int) -> bool:
	deadline = time.time() + seconds
	while time.time() < deadline:
		if provider.health():
			return True
		if not unit_active(unit):
			return False
		time.sleep(1)
	return False


def wait_http(provider: HTTPProvider, unit: str, seconds: int) -> bool:
	deadline = time.time() + seconds
	while time.time() < deadline:
		if provider.health():
			return True
		if not unit_active(unit):
			return False
		time.sleep(2)
	return False


def tail(path: Path, lines: int = 20) -> str:
	try:
		return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
	except OSError:
		return "(no log)"


def start_forge(
	unit: str,
	*,
	server: str,
	model: str,
	socket: str,
	log: Path,
	memory: str = "7G",
	ctx: int = 4096,
) -> None:
	cmd = [
		"/usr/bin/env",
		f"LD_LIBRARY_PATH={Path(server).parent}",
		server,
		"-m", model,
		"--host", socket,
		"--ctx-size", str(ctx),
		"--n-gpu-layers", "99",
		"--jinja",
		"--flash-attn", "on",
		"--no-webui",
	]
	start_unit(unit, cmd, log=log, memory=memory)


def start_loom(
	unit: str,
	*,
	flm_bin: str,
	model: str,
	log: Path,
	url: str = "http://127.0.0.1:52625",
	memory: str = "10G",
	ctx: int = 4096,
) -> None:
	port = url.rsplit(":", 1)[-1].rstrip("/") if ":" in url else "52625"
	cmd = [flm_bin, "serve", model, "--host", "127.0.0.1", "--port", port, "--ctx-len", str(ctx)]
	start_unit(unit, cmd, log=log, memory=memory)
