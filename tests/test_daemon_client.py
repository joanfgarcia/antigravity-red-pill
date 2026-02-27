"""
TCG-002: Memory Daemon Client Contract
======================================
Tests the _get_vector_from_daemon() client implementation in memory.py.
Validates the Length-Prefixed Framing (CQ-003) and the JSON contract
without requiring a live Unix socket or GPU-backed daemon.
"""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from red_pill.memory import MemoryManager


@pytest.fixture
def mock_socket():
	"""Mocks a successful Unix socket connection and response."""
	with patch("socket.socket") as mock_sock_cls:
		mock_conn = MagicMock()
		mock_sock_cls.return_value.__enter__.return_value = mock_conn
		yield mock_conn


def test_get_vector_from_daemon_success(mock_socket):
	"""Test successful embedding retrieval with correct framing."""
	# 1. Setup mock response (Length-prefixed JSON matching the daemon's contract)
	fake_vector = [0.1, 0.2, 0.3]
	resp_payload = json.dumps({"status": "ok", "vector": fake_vector}).encode("utf-8")
	resp_header = len(resp_payload).to_bytes(4, byteorder="big")

	# Mock recv to return header then payload
	mock_socket.recv.side_effect = [resp_header, resp_payload]

	# 2. Mock state (socket file must "exist" for the check)
	with patch("os.path.exists", return_value=True):
		manager = MemoryManager()
		result = manager._get_vector_from_daemon("test text")

	# 3. Assertions
	assert result == fake_vector

	# Verify framing: client sent 4-byte header then JSON
	sent_data = b"".join([call.args[0] for call in mock_socket.sendall.call_args_list])
	header_sent = sent_data[:4]
	payload_sent = sent_data[4:]

	sent_len = int.from_bytes(header_sent, byteorder="big")
	assert sent_len == len(payload_sent)
	assert json.loads(payload_sent.decode("utf-8"))["text"] == "test text"


def test_get_vector_from_daemon_no_socket_file():
	"""Retries should return None immediately if socket file is missing."""
	with patch("os.path.exists", return_value=False):
		manager = MemoryManager()
		result = manager._get_vector_from_daemon("test text")
		assert result is None


def test_get_vector_from_daemon_socket_error(mock_socket):
	"""Graceful handling of connection errors."""
	mock_socket.connect.side_effect = socket.error("Connection refused")

	with patch("os.path.exists", return_value=True):
		manager = MemoryManager()
		result = manager._get_vector_from_daemon("test text")
		assert result is None


def test_get_vector_from_daemon_malformed_response(mock_socket):
	"""Handling of malformed responses (bad header)."""
	mock_socket.recv.return_value = b""  # Immediate EOF

	with patch("os.path.exists", return_value=True):
		manager = MemoryManager()
		result = manager._get_vector_from_daemon("test text")
		assert result is None


def test_get_vector_from_daemon_timeout(mock_socket):
	"""Handling of socket timeouts."""
	mock_socket.recv.side_effect = socket.timeout()

	with patch("os.path.exists", return_value=True):
		manager = MemoryManager()
		result = manager._get_vector_from_daemon("test text")
		assert result is None
