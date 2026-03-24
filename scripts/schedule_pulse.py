#!/usr/bin/env python3
"""
schedule_pulse.py — Cross-Platform Red Pill Heartbeat Scheduler
=============================================================
Registers periodic oneshot tasks (Pulse, Telemetry, Queue).
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_INTERVAL_HOURS = 1
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIGGER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "trigger_pulse.py")

# Systemd unit names (Linux)
TIMER_NAME = "redpill-pulse.timer"
SERVICE_NAME = "redpill-pulse.service"
SYSTEMD_USER_DIR = os.path.expanduser("~/.config/systemd/user")

# Launchd label (macOS)
LAUNCHD_LABEL = "com.redpill.pulse"
LAUNCHD_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")

# Task Scheduler name (Windows)
TASK_NAME_PULSE = "RedPill-Pulse"
TASK_NAME_TELEMETRY = "RedPill-Telemetry"
TASK_NAME_QUEUE = "RedPill-Queue"

# Scripts
TRIGGER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "trigger_pulse.py")
TELEMETRY_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "bunker_telemetry.py")
QUEUE_SCRIPT = os.path.join(PROJECT_ROOT, "src", "red_pill", "core", "queue_worker.py")


def _find_uv() -> str:
	"""Return the absolute path to the uv binary."""
	uv = shutil.which("uv")
	if uv:
		return uv
	# Fallback: common install location
	candidate = os.path.expanduser("~/.local/bin/uv")
	if os.path.exists(candidate):
		return candidate
	print("[ERROR] 'uv' not found. Install it first: https://docs.astral.sh/uv/")
	sys.exit(1)


# ---------------------------------------------------------------------------
# Linux — systemd user timer
# ---------------------------------------------------------------------------


def _install_linux(interval_hours: int, uv_path: str) -> None:
	os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)

	# 1. Pulse (Maintenance) - Hourly
	_write_systemd_unit(SERVICE_NAME, f"{uv_path} run python {TRIGGER_SCRIPT}", "Red Pill Sovereign Pulse", type="oneshot")
	_write_systemd_timer(TIMER_NAME, f"{interval_hours}h", "Timer for Red Pill Sovereign Pulse")

	# 2. Telemetry (Heartbeat) - 10s-30s
	_write_systemd_unit(
		"redpill-telemetry.service", f"{uv_path} run python {TELEMETRY_SCRIPT} --oneshot", "Red Pill Telemetry Heartbeat", type="oneshot"
	)
	_write_systemd_timer("redpill-telemetry.timer", "30s", "Timer for Red Pill Telemetry Heartbeat")

	# 3. Queue (Worker) - 15m
	_write_systemd_unit("redpill-queue.service", f"{uv_path} run python {QUEUE_SCRIPT} --oneshot", "Red Pill Memory Queue Worker", type="oneshot")
	_write_systemd_timer("redpill-queue.timer", "15m", "Timer for Red Pill Memory Queue Worker")

	subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", TIMER_NAME], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-telemetry.timer"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-queue.timer"], check=True)
	print(f"[OK] systemd timers installed. Protocol Zero-Daemon active.")


def _write_systemd_unit(name, command, desc, type="oneshot"):
	path = os.path.join(SYSTEMD_USER_DIR, name)
	content = textwrap.dedent(f"""\
        [Unit]
        Description={desc}

        [Service]
        Type={type}
        WorkingDirectory={PROJECT_ROOT}
        Environment="PATH={os.environ.get("PATH")}"
        ExecStart={command}
    """)
	with open(path, "w") as f:
		f.write(content)


def _write_systemd_timer(name, interval, desc):
	path = os.path.join(SYSTEMD_USER_DIR, name)
	content = textwrap.dedent(f"""\
        [Unit]
        Description={desc}

        [Timer]
        OnBootSec=1min
        OnUnitActiveSec={interval}
        AccuracySec=1s
        Persistent=true

        [Install]
        WantedBy=timers.target
    """)
	with open(path, "w") as f:
		f.write(content)


def _uninstall_linux() -> None:
	subprocess.run(["systemctl", "--user", "disable", "--now", TIMER_NAME], check=False)
	subprocess.run(["systemctl", "--user", "disable", "--now", "redpill-telemetry.timer"], check=False)
	subprocess.run(["systemctl", "--user", "disable", "--now", "redpill-queue.timer"], check=False)
	for name in (TIMER_NAME, SERVICE_NAME, "redpill-telemetry.timer", "redpill-telemetry.service", "redpill-queue.timer", "redpill-queue.service"):
		path = os.path.join(SYSTEMD_USER_DIR, name)
		if os.path.exists(path):
			os.remove(path)
			print(f"[OK] Removed {path}")
	subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
	print("[OK] systemd pulse timer uninstalled.")


# ---------------------------------------------------------------------------
# macOS — launchd plist
# ---------------------------------------------------------------------------


def _uninstall_macos() -> None:
	if os.path.exists(LAUNCHD_PLIST):
		subprocess.run(["launchctl", "unload", LAUNCHD_PLIST], check=False)
		os.remove(LAUNCHD_PLIST)
		print(f"[OK] Removed {LAUNCHD_PLIST}")
	# Also uninstall telemetry and queue if they were separate (but here we'll keep them in one plist or multiple)
	# For now, let's assume we use separate plists for separate intervals.
	for suffix in ("telemetry", "queue"):
		p = os.path.expanduser(f"~/Library/LaunchAgents/com.redpill.{suffix}.plist")
		if os.path.exists(p):
			subprocess.run(["launchctl", "unload", p], check=False)
			os.remove(p)
			print(f"[OK] Removed {p}")
	print("[OK] launchd pulse agents uninstalled.")


def _install_macos(interval_hours: int, uv_path: str) -> None:
	# 1. Pulse
	_write_launchd_plist("com.redpill.pulse", f"{uv_path} run python {TRIGGER_SCRIPT}", interval_hours * 3600)
	# 2. Telemetry
	_write_launchd_plist("com.redpill.telemetry", f"{uv_path} run python {TELEMETRY_SCRIPT} --oneshot", 30)
	# 3. Queue
	_write_launchd_plist("com.redpill.queue", f"{uv_path} run python {QUEUE_SCRIPT} --oneshot", 15 * 60)
	print(f"[OK] launchd agents installed. Protocol Zero-Daemon active.")


def _write_launchd_plist(label, command, interval_seconds):
	plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
	args = command.split(" ")
	args_xml = "".join([f"<string>{a}</string>" for a in args])
	content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{label}</string>
            <key>ProgramArguments</key>
            <array>
                {args_xml}
            </array>
            <key>WorkingDirectory</key>
            <string>{PROJECT_ROOT}</string>
            <key>StartInterval</key>
            <integer>{interval_seconds}</integer>
            <key>RunAtLoad</key>
            <true/>
        </dict>
        </plist>
    """)
	os.makedirs(os.path.dirname(plist_path), exist_ok=True)
	with open(plist_path, "w") as f:
		f.write(content)
	subprocess.run(["launchctl", "unload", plist_path], check=False, stderr=subprocess.DEVNULL)
	subprocess.run(["launchctl", "load", plist_path], check=True)


# ---------------------------------------------------------------------------
# Windows — Task Scheduler
# ---------------------------------------------------------------------------


def _install_windows(interval_hours: int, uv_path: str) -> None:
	# 1. Pulse
	_create_win_task(TASK_NAME_PULSE, f'"{uv_path}" run python "{TRIGGER_SCRIPT}"', interval_hours * 60)
	# 2. Telemetry
	_create_win_task(TASK_NAME_TELEMETRY, f'"{uv_path}" run python "{TELEMETRY_SCRIPT}" --oneshot', 1)  # Min interval 1m in schtasks usually
	# 3. Queue
	_create_win_task(TASK_NAME_QUEUE, f'"{uv_path}" run python "{QUEUE_SCRIPT}" --oneshot', 15)
	print(f"[OK] Windows Tasks created. Protocol Zero-Daemon active.")


def _create_win_task(name, command, minutes):
	cmd = [
		"schtasks",
		"/create",
		"/tn",
		name,
		"/tr",
		f'cmd.exe /c cd /d "{PROJECT_ROOT}" && {command}',
		"/sc",
		"MINUTE",
		"/mo",
		str(minutes),
		"/f",
		"/rl",
		"HIGHEST",
	]
	subprocess.run(cmd, check=True)


def _uninstall_windows() -> None:
	for tn in (TASK_NAME_PULSE, TASK_NAME_TELEMETRY, TASK_NAME_QUEUE):
		subprocess.run(["schtasks", "/delete", "/tn", tn, "/f"], check=False)
	print("[OK] Windows tasks uninstalled.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
	parser = argparse.ArgumentParser(description="Cross-platform pulse scheduler for Red Pill.")
	parser.add_argument(
		"--interval-hours", type=int, default=DEFAULT_INTERVAL_HOURS, help=f"How often to run the pulse in hours (default: {DEFAULT_INTERVAL_HOURS})"
	)
	parser.add_argument("--uninstall", action="store_true", help="Remove the scheduled job for the current platform")
	args = parser.parse_args()

	system = platform.system()
	print(f"[INFO] Platform detected: {system}")

	if args.uninstall:
		if system == "Linux":
			_uninstall_linux()
		elif system == "Darwin":
			_uninstall_macos()
		elif system == "Windows":
			_uninstall_windows()
		else:
			print(f"[ERROR] Unsupported platform: {system}")
			sys.exit(1)
		return

	uv_path = _find_uv()
	print(f"[INFO] uv found at: {uv_path}")
	print(f"[INFO] trigger_pulse: {TRIGGER_SCRIPT}")
	print(f"[INFO] Interval: {args.interval_hours}h")

	if system == "Linux":
		_install_linux(args.interval_hours, uv_path)
	elif system == "Darwin":
		_install_macos(args.interval_hours, uv_path)
	elif system == "Windows":
		_install_windows(args.interval_hours, uv_path)
	else:
		print(f"[ERROR] Unsupported platform: {system}. Implement support or run trigger_pulse.py manually.")
		sys.exit(1)


if __name__ == "__main__":
	main()
