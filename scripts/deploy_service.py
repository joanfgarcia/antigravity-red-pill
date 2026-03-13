import os
import subprocess
import sys


def deploy_systemd_service():
	"""
	Deploys the Red Pill Sovereign CNS service (redpill.service) to systemd.
	This service ensures the Memory Sidecar and heartbeats are always running.
	"""
	home = os.path.expanduser("~")
	project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

	# Define paths
	service_dir = f"{home}/.config/systemd/user"
	os.makedirs(service_dir, exist_ok=True)

	service_path = f"{service_dir}/redpill.service"

	# Use absolute path for uv
	uv_path = os.path.join(home, ".local/bin/uv")

	# We use 'uv run red-pill daemon' to start the sidecar
	# This also starts the LazarusPulse internal rituals.

	service_content = f"""[Unit]
Description=Red Pill Sovereign CNS (Memory Sidecar & Pulse)
After=network.target

[Service]
Type=simple
WorkingDirectory={project_root}
Environment="PATH={home}/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart={uv_path} run red-pill daemon
Restart=always
StandardOutput=append:{home}/.agent/redpill.log
StandardError=append:{home}/.agent/redpill_error.log

[Install]
WantedBy=default.target
"""

	try:
		with open(service_path, "w") as f:
			f.write(service_content)

		print(f"--- [OK] Service unit created at: {service_path} ---")

		# Reload and start
		subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
		subprocess.run(["systemctl", "--user", "enable", "redpill.service"], check=True)
		subprocess.run(["systemctl", "--user", "restart", "redpill.service"], check=True)

		print("--- [OK] redpill.service is now ACTIVE and PERSISTENT ---")

	except Exception as e:
		print(f"--- [FAIL] Service deployment failed: {e} ---")
		sys.exit(1)


if __name__ == "__main__":
	deploy_systemd_service()
