#!/usr/bin/env python3
"""
schedule_pulse.py — Cross-Platform Lazarus Pulse Scheduler
===========================================================
Detects the current OS and registers the hourly heartbeat job using
the native scheduling mechanism:
  - Linux  → systemd user timer  (redpill-pulse.timer / .service)
  - macOS  → launchd plist       (~/Library/LaunchAgents/com.redpill.pulse.plist)
  - Windows → Task Scheduler     (schtasks /create ...)

Usage:
  uv run python scripts/schedule_pulse.py [--interval-hours N] [--uninstall]
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
TASK_NAME = "RedPill-Pulse"


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

    service_path = os.path.join(SYSTEMD_USER_DIR, SERVICE_NAME)
    timer_path = os.path.join(SYSTEMD_USER_DIR, TIMER_NAME)

    service_content = textwrap.dedent(f"""\
        [Unit]
        Description=Red Pill Sovereign Pulse

        [Service]
        Type=oneshot
        WorkingDirectory={PROJECT_ROOT}
        Environment="PATH={os.path.dirname(uv_path)}:/usr/local/bin:/usr/bin:/bin"
        ExecStart={uv_path} run python {TRIGGER_SCRIPT}
    """)

    timer_content = textwrap.dedent(f"""\
        [Unit]
        Description=Timer for Red Pill Sovereign Pulse

        [Timer]
        OnBootSec=5min
        OnUnitActiveSec={interval_hours}h
        Persistent=true

        [Install]
        WantedBy=timers.target
    """)

    with open(service_path, "w") as f:
        f.write(service_content)
    with open(timer_path, "w") as f:
        f.write(timer_content)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", TIMER_NAME], check=True)
    print(f"[OK] systemd timer installed. Next run in ~{interval_hours}h (also on next boot after 5min).")


def _uninstall_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", TIMER_NAME], check=False)
    for name in (TIMER_NAME, SERVICE_NAME):
        path = os.path.join(SYSTEMD_USER_DIR, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"[OK] Removed {path}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("[OK] systemd pulse timer uninstalled.")


# ---------------------------------------------------------------------------
# macOS — launchd plist
# ---------------------------------------------------------------------------

def _install_macos(interval_hours: int, uv_path: str) -> None:
    interval_seconds = interval_hours * 3600
    plist_content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{uv_path}</string>
                <string>run</string>
                <string>python</string>
                <string>{TRIGGER_SCRIPT}</string>
            </array>
            <key>WorkingDirectory</key>
            <string>{PROJECT_ROOT}</string>
            <key>StartInterval</key>
            <integer>{interval_seconds}</integer>
            <key>RunAtLoad</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{os.path.expanduser("~/.agent/redpill_pulse.log")}</string>
            <key>StandardErrorPath</key>
            <string>{os.path.expanduser("~/.agent/redpill_pulse_error.log")}</string>
        </dict>
        </plist>
    """)

    os.makedirs(os.path.dirname(LAUNCHD_PLIST), exist_ok=True)
    with open(LAUNCHD_PLIST, "w") as f:
        f.write(plist_content)

    # Unload previous version if it exists
    subprocess.run(["launchctl", "unload", LAUNCHD_PLIST], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "load", LAUNCHD_PLIST], check=True)
    print(f"[OK] launchd agent installed. Runs every {interval_hours}h (also at login).")


def _uninstall_macos() -> None:
    if os.path.exists(LAUNCHD_PLIST):
        subprocess.run(["launchctl", "unload", LAUNCHD_PLIST], check=False)
        os.remove(LAUNCHD_PLIST)
        print(f"[OK] Removed {LAUNCHD_PLIST}")
    print("[OK] launchd pulse agent uninstalled.")


# ---------------------------------------------------------------------------
# Windows — Task Scheduler
# ---------------------------------------------------------------------------

def _install_windows(interval_hours: int, uv_path: str) -> None:
    # Build the trigger interval string (PT1H = 1 hour in ISO 8601 duration)
    schedule = f"PT{interval_hours}H"

    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{uv_path}" run python "{TRIGGER_SCRIPT}"',
        "/sc", "MINUTE",
        "/mo", str(interval_hours * 60),
        "/sd", "01/01/2000",
        "/ri", str(interval_hours * 60),  # repetition interval
        "/du", "9999:00",                  # duration: forever
        "/f",                              # force overwrite
        "/rl", "HIGHEST",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"[OK] Windows Task Scheduler job '{TASK_NAME}' created (every {interval_hours}h).")
    else:
        print(f"[ERROR] schtasks failed: {result.stderr.strip()}")
        sys.exit(1)


def _uninstall_windows() -> None:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"[OK] Windows Task Scheduler job '{TASK_NAME}' removed.")
    else:
        print(f"[WARN] Could not remove task (may not exist): {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform pulse scheduler for Red Pill.")
    parser.add_argument("--interval-hours", type=int, default=DEFAULT_INTERVAL_HOURS,
                        help=f"How often to run the pulse in hours (default: {DEFAULT_INTERVAL_HOURS})")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the scheduled job for the current platform")
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
