import json
import os
import socket
import subprocess
import time
import pytest
from red_pill.memory_daemon import MemoryDaemon
import red_pill.config as cfg

@pytest.fixture
def run_daemon():
	"""Fixture to start and stop the daemon in a subprocess."""
	socket_path = cfg.DAEMON_SOCKET_PATH
	if os.path.exists(socket_path):
		os.remove(socket_path)
	
	# Start as subprocess
	proc = subprocess.Popen(["python3", "-m", "red_pill.memory_daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	
	# Wait for socket to appear
	retries = 10
	while not os.path.exists(socket_path) and retries > 0:
		time.sleep(0.5)
		retries -= 1
		
	if retries == 0:
		proc.kill()
		pytest.fail("Daemon failed to start and create socket.")
		
	yield proc
	
	proc.terminate()
	proc.wait()
	if os.path.exists(socket_path):
		os.remove(socket_path)

def test_daemon_ping_with_auth(run_daemon):
	"""Tests the daemon ping-pong with the new header and auth protocol."""
	socket_path = cfg.DAEMON_SOCKET_PATH
	with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
		client.settimeout(2.0)
		client.connect(socket_path)
		
		# Valid Request
		request = {"command": "ping", "api_key": cfg.QDRANT_API_KEY}
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
	socket_path = cfg.DAEMON_SOCKET_PATH
	with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
		client.settimeout(2.0)
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
