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

# Config
DEFAULT_INTERVAL_HOURS = 1
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Systemd unit names (Linux)
WAKE_SERVICE = "redpill-wake.service"
WAKE_TIMER = "redpill-wake.timer"
SLEEP_SERVICE = "redpill-sleep.service"
SLEEP_TIMER = "redpill-sleep.timer"
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
TELEMETRY_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "telemetry.py")
QUEUE_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "process_queue.py")
CHRONICLE_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "chronicle_daily.py")


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


# Linux — systemd user timer


def _install_linux(interval_hours: int, uv_path: str) -> None:
	os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)

	# 1. Wake Pulse (Hourly) — Social connectivity, swarm, hive sync
	_write_systemd_unit(WAKE_SERVICE, f"{uv_path} run python {TRIGGER_SCRIPT} --cycle wake", "Red Pill Wake Pulse", type="oneshot")
	_write_systemd_timer(WAKE_TIMER, f"{interval_hours}h", "Timer for Red Pill Wake Pulse (Hourly)")

	# 2. Sleep Pulse (03:00 Daily) — Memory consolidation, Ariadne's Thread
	_write_systemd_unit(SLEEP_SERVICE, f"{uv_path} run python {TRIGGER_SCRIPT} --cycle sleep", "Red Pill Sleep Pulse", type="oneshot", nice=10)
	_write_calendar_timer(SLEEP_TIMER, "*-*-* 03:00:00", "Daily Sleep Consolidation Pulse")

	# 3. Telemetry (Heartbeat) - 10s-30s
	_write_systemd_unit(
		"redpill-telemetry.service", f"{uv_path} run python {TELEMETRY_SCRIPT} --oneshot", "Red Pill Telemetry Heartbeat", type="oneshot"
	)
	_write_systemd_timer("redpill-telemetry.timer", "30s", "Timer for Red Pill Telemetry Heartbeat")

	# 3. Queue (Worker) - 1m
	_write_systemd_unit("redpill-queue.service", f"{uv_path} run python {QUEUE_SCRIPT} --oneshot", "Red Pill Memory Queue Worker", type="oneshot")
	_write_systemd_timer("redpill-queue.timer", "1m", "Timer for Red Pill Memory Queue Worker")

	# 4. Chronicle Daily (04:00, Persistent — runs on next boot if missed)
	_write_systemd_unit(
		"redpill-chronicle.service",
		f"{uv_path} run python {CHRONICLE_SCRIPT}",
		"Red Pill Chronicle Daily Pipeline",
		type="oneshot",
		nice=10,
	)
	_write_calendar_timer("redpill-chronicle.timer", "*-*-* 04:00:00", "Daily Chronicle Ingestion Pipeline")

	subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", WAKE_TIMER], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", SLEEP_TIMER], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-telemetry.timer"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-queue.timer"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-chronicle.timer"], check=True)
	print("[OK] systemd timers installed. Protocol Zero-Daemon active.")


def _write_systemd_unit(name, command, desc, type="oneshot", nice: int | None = None):
	path = os.path.join(SYSTEMD_USER_DIR, name)
	nice_line = f"\nNice={nice}" if nice is not None else ""
	content = textwrap.dedent(f"""\
		[Unit]
		Description={desc}

		[Service]
		Type={type}
		WorkingDirectory={PROJECT_ROOT}
		Environment="PATH={os.environ.get("PATH")}"
		ExecStart={command}{nice_line}
	""")
	with open(path, "w") as f:
		f.write(content)


def _write_calendar_timer(name: str, calendar: str, desc: str) -> None:
	"""Write a systemd timer that fires at a fixed calendar time (not interval).
	Uses Persistent=true so it fires on next boot/wake if the system was off.
	"""
	path = os.path.join(SYSTEMD_USER_DIR, name)
	content = textwrap.dedent(f"""\
		[Unit]
		Description={desc}

		[Timer]
		OnCalendar={calendar}
		Persistent=true
		WakeSystem=false
		AccuracySec=5min

		[Install]
		WantedBy=timers.target
	""")
	with open(path, "w") as f:
		f.write(content)


def _write_systemd_timer(name, interval, desc):
	path = os.path.join(SYSTEMD_USER_DIR, name)
	content = textwrap.dedent(f"""\
		[Unit]
		Description={desc}

		[Timer]
		OnActiveSec=5s
		OnUnitInactiveSec={interval}
		AccuracySec=1s
		Persistent=true

		[Install]
		WantedBy=timers.target
	""")
	with open(path, "w") as f:
		f.write(content)


def _uninstall_linux() -> None:
	for timer in (WAKE_TIMER, SLEEP_TIMER, "redpill-telemetry.timer", "redpill-queue.timer", "redpill-chronicle.timer"):
		subprocess.run(["systemctl", "--user", "disable", "--now", timer], check=False)
	for name in (
		WAKE_TIMER,
		WAKE_SERVICE,
		SLEEP_TIMER,
		SLEEP_SERVICE,
		"redpill-telemetry.timer",
		"redpill-telemetry.service",
		"redpill-queue.timer",
		"redpill-queue.service",
		"redpill-chronicle.timer",
		"redpill-chronicle.service",
	):
		path = os.path.join(SYSTEMD_USER_DIR, name)
		if os.path.exists(path):
			os.remove(path)
			print(f"[OK] Removed {path}")
	subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
	print("[OK] systemd pulse timers uninstalled.")


# macOS — launchd plist


def _uninstall_macos() -> None:
	for label in ("wake", "sleep", "telemetry", "queue"):
		p = os.path.expanduser(f"~/Library/LaunchAgents/com.redpill.{label}.plist")
		if os.path.exists(p):
			subprocess.run(["launchctl", "unload", p], check=False)
			os.remove(p)
			print(f"[OK] Removed {p}")
	# Legacy cleanup
	if os.path.exists(LAUNCHD_PLIST):
		subprocess.run(["launchctl", "unload", LAUNCHD_PLIST], check=False)
		os.remove(LAUNCHD_PLIST)
	print("[OK] launchd pulse agents uninstalled.")


def _install_macos(interval_hours: int, uv_path: str) -> None:
	# 1. Wake Pulse (Interval-based, hourly)
	_write_launchd_plist("com.redpill.wake", f"{uv_path} run python {TRIGGER_SCRIPT} --cycle wake", interval_hours * 3600)
	# 2. Sleep Pulse (Calendar-based, 03:00 daily)
	_write_launchd_calendar_plist("com.redpill.sleep", f"{uv_path} run python {TRIGGER_SCRIPT} --cycle sleep", hour=3, minute=0)
	# 3. Telemetry
	_write_launchd_plist("com.redpill.telemetry", f"{uv_path} run python {TELEMETRY_SCRIPT} --oneshot", 30)
	# 4. Queue
	_write_launchd_plist("com.redpill.queue", f"{uv_path} run python {QUEUE_SCRIPT} --oneshot", 60)
	print("[OK] launchd agents installed. Protocol Zero-Daemon active.")


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


def _write_launchd_calendar_plist(label: str, command: str, hour: int, minute: int) -> None:
	"""Write a launchd plist that fires at a fixed daily time (StartCalendarInterval)."""
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
			<key>StartCalendarInterval</key>
			<dict>
				<key>Hour</key>
				<integer>{hour}</integer>
				<key>Minute</key>
				<integer>{minute}</integer>
			</dict>
		</dict>
		</plist>
	""")
	os.makedirs(os.path.dirname(plist_path), exist_ok=True)
	with open(plist_path, "w") as f:
		f.write(content)
	subprocess.run(["launchctl", "unload", plist_path], check=False, stderr=subprocess.DEVNULL)
	subprocess.run(["launchctl", "load", plist_path], check=True)


# Windows — Task Scheduler


def _install_windows(interval_hours: int, uv_path: str) -> None:
	# 1. Wake Pulse (interval — MINUTE-based)
	_create_win_task("RedPill-Wake", f'"{uv_path}" run python "{TRIGGER_SCRIPT}" --cycle wake', interval_hours * 60)
	# 2. Sleep Pulse (daily at 03:00)
	_create_win_daily_task("RedPill-Sleep", f'"{uv_path}" run python "{TRIGGER_SCRIPT}" --cycle sleep', "03:00")
	# 3. Telemetry
	_create_win_task(TASK_NAME_TELEMETRY, f'"{uv_path}" run python "{TELEMETRY_SCRIPT}" --oneshot', 1)
	# 4. Queue
	_create_win_task(TASK_NAME_QUEUE, f'"{uv_path}" run python "{QUEUE_SCRIPT}" --oneshot', 1)
	print("[OK] Windows Tasks created. Protocol Zero-Daemon active.")


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


def _create_win_daily_task(name: str, command: str, start_time: str) -> None:
	"""Create a Windows Task Scheduler task that runs daily at a fixed time."""
	cmd = [
		"schtasks",
		"/create",
		"/tn",
		name,
		"/tr",
		f'cmd.exe /c cd /d "{PROJECT_ROOT}" && {command}',
		"/sc",
		"DAILY",
		"/st",
		start_time,
		"/f",
		"/rl",
		"HIGHEST",
	]
	subprocess.run(cmd, check=True)


def _uninstall_windows() -> None:
	for tn in ("RedPill-Wake", "RedPill-Sleep", TASK_NAME_TELEMETRY, TASK_NAME_QUEUE):
		subprocess.run(["schtasks", "/delete", "/tn", tn, "/f"], check=False)
	# Legacy cleanup
	subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME_PULSE, "/f"], check=False)
	print("[OK] Windows tasks uninstalled.")


# Main


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
