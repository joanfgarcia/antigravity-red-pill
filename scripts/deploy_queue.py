import os
import subprocess
import sys


def deploy_linux():
	print("Deploying queue worker for Linux (Systemd Service)...")
	service_content = f"""[Unit]
Description=Bünker Asynchronous Memory Queue Worker
After=network.target

[Service]
Type=simple
WorkingDirectory={os.getcwd()}
Environment="PATH={os.environ.get('PATH', '/usr/bin:/bin')}"
ExecStart=/usr/bin/env uv run python src/red_pill/core/queue_worker.py
Restart=always
RestartSec=5
StandardOutput=append:{os.path.expanduser("~/.agent/queue_worker.log")}
StandardError=append:{os.path.expanduser("~/.agent/queue_worker_error.log")}

[Install]
WantedBy=default.target
"""
	config_dir = os.path.expanduser("~/.config/systemd/user")
	os.makedirs(config_dir, exist_ok=True)

	service_path = os.path.join(config_dir, "bunker-queue.service")
	with open(service_path, "w") as f:
		f.write(service_content)

	subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
	subprocess.run(["systemctl", "--user", "enable", "--now", "bunker-queue.service"], check=True)
	print("Systemd Service activated and running.")


def deploy_mac():
	print("Deploying queue worker for macOS (Launchd)...")
	cwd = os.getcwd()
	log_path = os.path.expanduser("~/.agent/queue_worker.log")
	err_path = os.path.expanduser("~/.agent/queue_worker_error.log")
	os.makedirs(os.path.dirname(log_path), exist_ok=True)
	
	plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.redpill.queue</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/env</string>
		<string>uv</string>
		<string>run</string>
		<string>python</string>
		<string>src/red_pill/core/queue_worker.py</string>
	</array>
	<key>WorkingDirectory</key>
	<string>{cwd}</string>
	<key>KeepAlive</key>
	<true/>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardOutPath</key>
	<string>{log_path}</string>
	<key>StandardErrorPath</key>
	<string>{err_path}</string>
</dict>
</plist>"""
	launch_dir = os.path.expanduser("~/Library/LaunchAgents")
	os.makedirs(launch_dir, exist_ok=True)
	plist_path = os.path.join(launch_dir, "com.redpill.queue.plist")

	with open(plist_path, "w") as f:
		f.write(plist_content)

	subprocess.run(["launchctl", "unload", plist_path], check=False, capture_output=True)
	subprocess.run(["launchctl", "load", plist_path], check=True)
	print("Launchd agent loaded and running.")


def deploy_windows():
	print("Deploying queue worker for Windows (Task Scheduler)...")
	cwd = os.getcwd()
	# Run on logon, indefinitely
	command = (
		f'schtasks /create /f /sc ONLOGON /tn "RedPillQueueWorker" /tr "cmd.exe /c cd /d {cwd} && uv run python src\\\\red_pill\\\\core\\\\queue_worker.py"'
	)
	subprocess.run(command, shell=True, check=True)
	# Also try starting it immediately
	try:
		subprocess.run('schtasks /run /tn "RedPillQueueWorker"', shell=True, check=True)
	except Exception:
		print("Task created but could not start immediately. Will start on next logon.")
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
