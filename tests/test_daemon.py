import json
import os

os.environ["QDRANT_API_KEY"] = "test_dummy_key_760"
os.environ["SIDECAR_AUTH_KEY"] = "test_sidecar_key_760"

import socket
import subprocess
import time

import pytest


@pytest.fixture
def run_daemon():
	"""Fixture to start and stop the daemon in a subprocess."""
	socket_path = "/tmp/red_pill_test.sock"
	if os.path.exists(socket_path):
		os.remove(socket_path)

	# Start as subprocess
	env = os.environ.copy()
	src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
	env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"
	env["DAEMON_SOCKET_PATH"] = socket_path
	env["SIDECAR_AUTH_KEY"] = "test_sidecar_key_760"

	# Use exactly the same command as systemd / CLI
	proc = subprocess.Popen(["uv", "run", "python", "-m", "red_pill.memory_daemon"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)

	# Wait for socket to appear
	retries = 30
	while not os.path.exists(socket_path) and retries > 0:
		time.sleep(0.5)
		retries -= 1

	if retries == 0:
		stdout, stderr = proc.communicate(timeout=2)
		proc.kill()
		pytest.fail(f"Daemon failed to start and create socket.\nStdout: {stdout}\nStderr: {stderr}")

	yield # This is where the daemon is running for the test

	# Teardown: Stop the daemon and clean up
	proc.terminate()
	try:
		proc.wait(timeout=5)
	except subprocess.TimeoutExpired:
		proc.kill()
	if os.path.exists(socket_path):
		os.remove(socket_path)


def test_daemon_ping_with_auth(run_daemon):
	"""Tests the daemon ping-pong with the new header and auth protocol."""
	socket_path = "/tmp/red_pill_test.sock"
	with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
		client.settimeout(10.0)
		client.connect(socket_path)

		# Valid Request
		request = {"command": "ping", "api_key": "test_sidecar_key_760"}
		payload = json.dumps(request).encode("utf-8")
		header = len(payload).to_bytes(4, byteorder="big")
		client.sendall(header + payload)

		# Read Response Header
		resp_header = client.recv(4)
		assert len(resp_header) == 4
		resp_len = int.from_bytes(resp_header, byteorder="big")

		# Read Response Body
		resp_data = client.recv(resp_len)
		response = json.loads(resp_data.decode("utf-8"))
		assert response["status"] == "ok"
		assert response["message"] == "pong"


def test_daemon_unauthorized_access(run_daemon):
	"""Tests that the daemon rejects requests with invalid API keys."""
	socket_path = "/tmp/red_pill_test.sock"
	with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
		client.settimeout(10.0)
		client.connect(socket_path)

		request = {"command": "ping", "api_key": "WRONG_KEY"}
		payload = json.dumps(request).encode("utf-8")
		header = len(payload).to_bytes(4, byteorder="big")
		client.sendall(header + payload)

		resp_header = client.recv(4)
		resp_len = int.from_bytes(resp_header, byteorder="big")
		resp_data = client.recv(resp_len)
		response = json.loads(resp_data.decode("utf-8"))
		assert response["status"] == "error"
		assert "Unauthorized" in response["message"]
