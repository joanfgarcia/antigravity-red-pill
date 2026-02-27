import json
import os
import socket
import threading
import time
from unittest.mock import patch

import pytest

from red_pill.memory import MemoryManager


@pytest.fixture
def manager():
	return MemoryManager()


def test_get_vector_from_daemon_isolation(manager):
	"""TCG-002: Isolates the daemon client path and validates framing and auth propagation."""
	socket_path = "/tmp/test_isolate_client.sock"
	if os.path.exists(socket_path):
		os.remove(socket_path)

	# Mock server to receive and respond
	def mock_server():
		with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
			server.settimeout(2)
			server.bind(socket_path)
			server.listen(1)
			try:
				conn, _ = server.accept()
				with conn:
					# Read length
					header = conn.recv(4)
					length = int.from_bytes(header, "big")
					payload_data = conn.recv(length)
					request = json.loads(payload_data.decode("utf-8"))

					# Validate client sent the correct API key from config
					if request["api_key"] == "test_secret_770":
						response = {"status": "ok", "vector": [1.0, 2.0, 3.0]}
					else:
						response = {"status": "error", "message": "unauthorized"}

					resp_payload = json.dumps(response).encode("utf-8")
					conn.sendall(len(resp_payload).to_bytes(4, "big") + resp_payload)
			except Exception:
				pass

	thread = threading.Thread(target=mock_server)
	thread.start()

	# Wait for socket
	for _ in range(10):
		if os.path.exists(socket_path):
			break
		time.sleep(0.1)

	try:
		# Use custom socket path and secret
		with patch("red_pill.config.DAEMON_SOCKET_PATH", socket_path), patch("red_pill.config.SIDECAR_AUTH_KEY", "test_secret_770"):
			vector = manager._get_vector_from_daemon("test text")
			assert vector == [1.0, 2.0, 3.0]
	finally:
		if os.path.exists(socket_path):
			os.remove(socket_path)
		thread.join(timeout=1)
