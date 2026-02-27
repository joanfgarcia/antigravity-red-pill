import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from red_pill.memory_daemon import MemoryDaemon


@pytest.fixture
def daemon():
	d = MemoryDaemon()
	d.encoder = MagicMock()
	# Mock the embedding to return a deterministic list
	d.encoder.embed.return_value = [MagicMock(tolist=lambda: [0.1, 0.2, 0.3])]
	return d


def test_handle_connection_success(daemon):
	"""TCG-001: Tests successful authenticated embedding request."""
	mock_conn = MagicMock(spec=socket.socket)

	# Request data
	req_data = {"text": "test memory", "api_key": "valid_key"}
	payload = json.dumps(req_data).encode("utf-8")
	header = len(payload).to_bytes(4, "big")

	# Mock recv: first call gets header, second gets payload
	mock_conn.recv.side_effect = [header, payload]

	with patch("red_pill.config.SIDECAR_AUTH_KEY", "valid_key"):
		daemon.handle_connection(mock_conn)

	# Verify response
	args, _ = mock_conn.sendall.call_args
	resp_full = args[0]
	resp_len = int.from_bytes(resp_full[:4], "big")
	resp_body = json.loads(resp_full[4:].decode("utf-8"))

	assert resp_body["status"] == "ok"
	assert resp_body["vector"] == [0.1, 0.2, 0.3]
	assert resp_len == len(resp_full) - 4


def test_handle_connection_unauthorized(daemon):
	"""SEC-004: Tests rejected request with invalid HMAC/key."""
	mock_conn = MagicMock(spec=socket.socket)

	req_data = {"text": "test", "api_key": "wrong_key"}
	payload = json.dumps(req_data).encode("utf-8")
	header = len(payload).to_bytes(4, "big")

	mock_conn.recv.side_effect = [header, payload]

	with patch("red_pill.config.SIDECAR_AUTH_KEY", "valid_key"):
		daemon.handle_connection(mock_conn)

	args, _ = mock_conn.sendall.call_args
	resp_body = json.loads(args[0][4:].decode("utf-8"))
	assert resp_body["status"] == "error"
	assert "Unauthorized" in resp_body["message"]


def test_handle_connection_ping(daemon):
	"""Tests the 'ping' command."""
	mock_conn = MagicMock(spec=socket.socket)

	req_data = {"command": "ping", "api_key": "valid_key"}
	payload = json.dumps(req_data).encode("utf-8")
	header = len(payload).to_bytes(4, "big")

	mock_conn.recv.side_effect = [header, payload]

	with patch("red_pill.config.SIDECAR_AUTH_KEY", "valid_key"):
		daemon.handle_connection(mock_conn)

	args, _ = mock_conn.sendall.call_args
	resp_body = json.loads(args[0][4:].decode("utf-8"))
	assert resp_body["status"] == "ok"
	assert resp_body["message"] == "pong"


def test_handle_connection_malformed_json(daemon):
	"""Tests resilience against malformed JSON payloads."""
	mock_conn = MagicMock(spec=socket.socket)

	payload = b"{invalid_json"
	header = len(payload).to_bytes(4, "big")

	mock_conn.recv.side_effect = [header, payload]

	daemon.handle_connection(mock_conn)

	args, _ = mock_conn.sendall.call_args
	resp_body = json.loads(args[0][4:].decode("utf-8"))
	assert resp_body["status"] == "error"
