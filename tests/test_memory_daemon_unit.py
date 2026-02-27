import json
import os
import socket
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from red_pill.memory_daemon import MemoryDaemon


@pytest.fixture
def mock_encoder():
	with patch("red_pill.memory_daemon.TextEmbedding") as mock:
		mock_inst = MagicMock()
		mock_inst.embed.return_value = [MagicMock(tolist=lambda: [0.1, 0.2])]
		mock.return_value = mock_inst
		yield mock


def test_daemon_encryption_check_no_crash():
	"""Ensures _check_encryption doesn't crash even if tools are missing."""
	daemon = MemoryDaemon()
	with patch("subprocess.run") as mock_run:
		mock_run.side_effect = Exception("tool not found")
		daemon._check_encryption()


def test_daemon_load_model_providers(mock_encoder):
	"""Tests model loading with hardware provider detection."""
	daemon = MemoryDaemon()
	with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), patch("os.path.exists", return_value=False):
		daemon._load_model()
		assert "CUDAExecutionProvider" in mock_encoder.call_args[1]["providers"]


def test_daemon_lifecycle_and_hmac(mock_encoder):
	"""TCG-001: Tests MemoryDaemon server loop, protocol, and HMAC verification."""
	socket_path = "/tmp/test_daemon_unit.sock"
	if os.path.exists(socket_path):
		os.remove(socket_path)

	daemon = MemoryDaemon()
	# Override socket path and secret for test
	# Note: We must patch red_pill.memory_daemon.SOCKET_PATH because it's evaluated at import time.
	with patch("red_pill.memory_daemon.SOCKET_PATH", socket_path), patch("red_pill.config.SIDECAR_AUTH_KEY", "test_secret"):
		# Start daemon in a thread
		daemon_thread = threading.Thread(target=daemon.start)

		daemon_thread = threading.Thread(target=daemon.start)
		daemon_thread.daemon = True
		daemon_thread.start()

		# Wait for socket
		for _ in range(10):
			if os.path.exists(socket_path):
				break
			time.sleep(0.1)

		try:
			# 1. Test Valid HMAC
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.connect(socket_path)
				req = {"text": "hello", "api_key": "test_secret"}
				payload = json.dumps(req).encode("utf-8")
				client.sendall(len(payload).to_bytes(4, "big") + payload)

				resp_header = client.recv(4)
				resp_len = int.from_bytes(resp_header, "big")
				resp_data = client.recv(resp_len)
				resp = json.loads(resp_data.decode("utf-8"))
				assert resp["status"] == "ok"
				assert resp["vector"] == [0.1, 0.2]

			# 2. Test Invalid HMAC
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.connect(socket_path)
				req = {"text": "hello", "api_key": "wrong_secret"}
				payload = json.dumps(req).encode("utf-8")
				client.sendall(len(payload).to_bytes(4, "big") + payload)

				resp_header = client.recv(4)
				resp_len = int.from_bytes(resp_header, "big")
				resp_data = client.recv(resp_len)
				resp = json.loads(resp_data.decode("utf-8"))
				assert resp["status"] == "error"
				assert "Unauthorized" in resp["message"]

		finally:
			daemon.stop()
			if os.path.exists(socket_path):
				os.remove(socket_path)
