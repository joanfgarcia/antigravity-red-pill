import hmac
import json
import os
import socket
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory_daemon import MemoryDaemon

@pytest.fixture
def mock_encoder():
	import numpy as np
	with patch("red_pill.memory_daemon.TextEmbedding") as mock:
		instance = mock.return_value
		instance.embed.return_value = [np.array([0.1, 0.2, 0.3])]
		yield instance

@pytest.fixture
def daemon(mock_encoder, tmp_path):
	# Override socket path for testing
	test_socket = str(tmp_path / "test_daemon.sock")
	with patch("red_pill.memory_daemon.SOCKET_PATH", test_socket):
		daemon = MemoryDaemon()
		# Start in a thread
		thread = threading.Thread(target=daemon.start)
		thread.daemon = True
		thread.start()
		
		# Give it a moment to start
		time.sleep(0.1)
		yield test_socket, daemon
		
		daemon.stop()
		thread.join(timeout=1.0)

def send_request(sock_path, request):
	client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	client.connect(sock_path)
	
	payload = json.dumps(request).encode("utf-8")
	header = len(payload).to_bytes(4, byteorder="big")
	client.sendall(header + payload)
	
	# Read response
	resp_header = client.recv(4)
	if not resp_header:
		return None
	resp_len = int.from_bytes(resp_header, byteorder="big")
	
	data = b""
	while len(data) < resp_len:
		chunk = client.recv(min(resp_len - len(data), 8192))
		if not chunk:
			break
		data += chunk
	
	client.close()
	return json.loads(data.decode("utf-8"))

def test_daemon_ping(daemon):
	sock_path, _ = daemon
	request = {
		"api_key": str(cfg.SIDECAR_AUTH_KEY or "").strip(),
		"command": "ping"
	}
	response = send_request(sock_path, request)
	assert response["status"] == "ok"
	assert response["message"] == "pong"

def test_daemon_unauthorized(daemon):
	sock_path, _ = daemon
	request = {
		"api_key": "wrong_key",
		"command": "ping"
	}
	response = send_request(sock_path, request)
	assert response["status"] == "error"
	assert "Unauthorized" in response["message"]

def test_daemon_embed(daemon, mock_encoder):
	sock_path, _ = daemon
	request = {
		"api_key": str(cfg.SIDECAR_AUTH_KEY or "").strip(),
		"text": "Hello world"
	}
	response = send_request(sock_path, request)
	assert response["status"] == "ok", f"Error: {response.get('message')}"
	assert response["vector"] == [0.1, 0.2, 0.3]
	mock_encoder.embed.assert_called_with(["Hello world"])

def test_daemon_empty_request(daemon):
	sock_path, _ = daemon
	# Send invalid JSON
	client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	client.connect(sock_path)
	client.sendall(b"\x00\x00\x00\x02{}") # Valid header but empty request
	resp_header = client.recv(4)
	assert resp_header
	client.close()

def test_daemon_large_payload(daemon):
	sock_path, _ = daemon
	large_text = "A" * 10000
	request = {
		"api_key": str(cfg.SIDECAR_AUTH_KEY or "").strip(),
		"text": large_text
	}
	response = send_request(sock_path, request)
	assert response["status"] == "ok", f"Error: {response.get('message')}"
