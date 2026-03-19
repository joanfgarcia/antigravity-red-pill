import os
import subprocess
import sys


def deploy_linux():
	print("Deploying for Linux (Systemd Timer)...")
	service_content = f"""[Unit]
Description=Red Pill Sovereign Pulse

[Service]
Type=oneshot
WorkingDirectory={os.getcwd()}
ExecStart=/usr/bin/env uv run python scripts/trigger_pulse.py
"""
	timer_content = """[Unit]
Description=Timer for Red Pill Sovereign Pulse

[Timer]
OnUnitActiveSec=2h
Persistent=true

[Install]
WantedBy=timers.target
"""
	config_dir = os.path.expanduser("~/.config/systemd/user")
	os.makedirs(config_dir, exist_ok=True)

	with open(os.path.join(config_dir, "redpill-pulse.service"), "w") as f:
		f.write(service_content)
	with open(os.path.join(config_dir, "redpill-pulse.timer"), "w") as f:
		f.write(timer_content)

	subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "redpill-pulse.timer"], check=True)
	print("Systemd Timer activated.")


def deploy_mac():
	print("Deploying for macOS (Launchd)...")
	cwd = os.getcwd()
	plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.redpill.pulse</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>uv</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/trigger_pulse.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd}</string>
    <key>StartInterval</key>
    <integer>7200</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
	launch_dir = os.path.expanduser("~/Library/LaunchAgents")
	os.makedirs(launch_dir, exist_ok=True)
	plist_path = os.path.join(launch_dir, "com.redpill.pulse.plist")

	with open(plist_path, "w") as f:
		f.write(plist_content)

	subprocess.run(["launchctl", "unload", plist_path], check=False, capture_output=True)
	subprocess.run(["launchctl", "load", plist_path], check=True)
	print("Launchd agent loaded.")


def deploy_windows():
	print("Deploying for Windows (Task Scheduler)...")
	cwd = os.getcwd()
	command = (
		f'schtasks /create /f /sc HOURLY /mo 2 /tn "RedPillPulse" /tr "cmd.exe /c cd /d {cwd} && uv run python scripts\\\\trigger_pulse.py" /st 00:00'
	)
	subprocess.run(command, shell=True, check=True)
	print("Windows Task Scheduler configured.")


if __name__ == "__main__":
	if sys.platform.startswith("linux"):
		deploy_linux()
	elif sys.platform == "darwin":
		deploy_mac()
	elif sys.platform == "win32":
		deploy_windows()
	else:
		print(f"Unsupported OS: {sys.platform}")
