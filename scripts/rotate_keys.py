import base64
import logging
import os
import subprocess
import sys
import platformdirs

# Ensure we can import red_pill
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("key_rotator")


def generate_key():
	return base64.b64encode(os.urandom(32)).decode("utf-8").replace("=", "").replace("+", "").replace("/", "")[:32]


def update_env_file(new_key):
	env_path = os.path.join(platformdirs.user_config_dir("red-pill"), ".env")
	if not os.path.exists(env_path):
		logger.error(f".env file not found at {env_path}")
		return False

	lines = []
	with open(env_path, "r") as f:
		lines = f.readlines()

	with open(env_path, "w") as f:
		found = False
		for line in lines:
			if line.startswith("QDRANT_API_KEY="):
				f.write(f"QDRANT_API_KEY={new_key}\n")
				found = True
			else:
				f.write(line)
		if not found:
			f.write(f"QDRANT_API_KEY={new_key}\n")

	logger.info("✓ .env file updated with new QDRANT_API_KEY.")
	return True


def update_systemd_quadlet(new_key):
	if sys.platform != "linux":
		return True  # Skip on non-linux

	quadlet_path = os.path.expanduser("~/.config/containers/systemd/qdrant.container")
	if not os.path.exists(quadlet_path):
		logger.warning(f"Quadlet file not found at {quadlet_path}. Ensure Qdrant is managed via systemd.")
		return False

	with open(quadlet_path, "r") as f:
		lines = f.readlines()

	with open(quadlet_path, "w") as f:
		for line in lines:
			if line.startswith("Environment=QDRANT__SERVICE__API_KEY="):
				f.write(f"Environment=QDRANT__SERVICE__API_KEY={new_key}\n")
			else:
				f.write(line)

	logger.info("✓ Quadlet configuration updated.")

	# Reload and Restart
	try:
		subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
		subprocess.run(["systemctl", "--user", "restart", "qdrant.service"], check=True)
		logger.info("✓ Qdrant service restarted with new API Key.")
	except Exception as e:
		logger.error(f"Failed to restart Qdrant: {e}")
		return False

	# SEC-01: Health check verification
	import time
	import urllib.request

	from red_pill import config as cfg

	health_ok = False
	for i in range(5):
		time.sleep(2)
		try:
			req = urllib.request.Request(f"{cfg.QDRANT_URL}/collections", headers={"api-key": new_key})
			with urllib.request.urlopen(req, timeout=2) as r:
				if r.status == 200:
					health_ok = True
					break
		except Exception as he:
			logger.debug(f"Health check loop {i + 1} failing gracefully: {he}")

	if not health_ok:
		logger.error("x Health check failed. The new API key was not accepted by Qdrant. Manual intervention needed.")
		return False

	logger.info("✓ Health check Passed. Qdrant is accepting the new key.")
	return True


def rotate():
	print("\n--- [RED PILL: API KEY ROTATION SEQUENCE] ---")
	new_key = generate_key()

	if update_env_file(new_key):
		if update_systemd_quadlet(new_key):
			print("\nSUCCESS: API Key rotated.")
			# SEC-005: Mask new API key to prevent terminal logging leaks
			masked_key = new_key[:4] + "*" * (len(new_key) - 8) + new_key[-4:]
			print(f"New Key: {masked_key}")

			print("Note: If using MCP, you may need to restart your IDE for the .env changes to propagate.")
		else:
			print("\nWARNING: .env updated but service restart failed. Manual intervention required.")
	else:
		print("\nFAILURE: Could not update .env file.")


if __name__ == "__main__":
	rotate()
