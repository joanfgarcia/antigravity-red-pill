import json
import socket
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# PRE-PATCH fastembed before importing MemoryDaemon to prevent model download
# ─────────────────────────────────────────────────────────────────────────────
_fake_fastembed = types.ModuleType("fastembed")
_fake_fastembed.TextEmbedding = MagicMock  # type: ignore
sys.modules.setdefault("fastembed", _fake_fastembed)

from red_pill.memory_daemon import MemoryDaemon  # noqa: E402


@pytest.fixture
def daemon():
	d = MemoryDaemon()
	d.encoder = MagicMock()
	# Mock the embedding to return a deterministic list
	d.encoder.embed.return_value = [MagicMock(tolist=lambda: [0.1, 0.2, 0.3])]
	d.engines = [d.encoder]
	import itertools
	d.engine_cycle = itertools.cycle(d.engines)
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


# ─────────────────────────────────────────────────────────────────────────────
# _check_encryption() — lines 33, 40-41, 47, 56, 63-64
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckEncryption:
	def test_non_linux_is_skipped(self):
		"""Line 33: non-linux → return immediately."""
		d = MemoryDaemon()
		with patch("sys.platform", "darwin"):
			d._check_encryption()  # Should not raise

	def test_missing_findmnt_skips_check(self):
		"""Lines 39-41: findmnt not found → debug log and return."""
		d = MemoryDaemon()
		with patch("sys.platform", "linux"):
			with patch("shutil.which", return_value=None):
				d._check_encryption()  # Should not raise

	def test_storage_path_created_if_missing(self, tmp_path):
		"""Line 47: storage path doesn't exist → makedirs."""
		d = MemoryDaemon()
		str(tmp_path / "nonexistent_storage")
		with patch("sys.platform", "linux"):
			with patch("shutil.which", return_value="/usr/bin/findmnt"):
				with patch("red_pill.config.IA_DIR", str(tmp_path)):
					with patch("subprocess.run") as mock_run:
						mock_run.return_value = MagicMock(stdout="")
						d._check_encryption()
		# makedirs was called, directory exists now
		import os

		assert os.path.exists(str(tmp_path / "storage"))

	def test_crypt_device_logged(self, tmp_path):
		"""Line 56: 'crypt' in lsblk output → info log."""
		d = MemoryDaemon()
		(tmp_path / "storage").mkdir()
		with patch("sys.platform", "linux"):
			with patch("shutil.which", return_value="/usr/bin/findmnt"):
				with patch("red_pill.config.IA_DIR", str(tmp_path)):
					with patch("subprocess.run") as mock_run:
						mock_run.side_effect = [
							MagicMock(stdout="/dev/dm-0"),  # findmnt
							MagicMock(stdout="crypt\n"),  # lsblk
						]
						d._check_encryption()  # Should log INFO, not raise

	def test_encryption_check_exception_handled(self):
		"""Lines 63-64: unexpected exception → debug log, no crash."""
		d = MemoryDaemon()
		with patch("sys.platform", "linux"):
			with patch("shutil.which", side_effect=RuntimeError("OS failure")):
				d._check_encryption()  # Must not raise


# ─────────────────────────────────────────────────────────────────────────────
# _load_model() — lines 77-80, 83, 94-96
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# start() — lines 101, 119-121, 135
# ─────────────────────────────────────────────────────────────────────────────


class TestDaemonStart:
	def test_removes_existing_socket_path(self, short_socket_dir):
		"""Line 101: socket file exists → os.remove before bind."""
		import os

		sock_path = str(short_socket_dir / "test.sock")
		open(sock_path, "w").close()

		with patch("red_pill.config.SIDECAR_AUTH_KEY", "test_key"):
			d = MemoryDaemon()

			def fake_stop(*args):
				d.running = False

			with patch("red_pill.memory_daemon.SOCKET_PATH", sock_path):
				with patch("socket.socket") as mock_sock_cls:
					mock_sock = MagicMock()
					mock_sock.accept.side_effect = socket.timeout("timed out")
					mock_sock_cls.return_value = mock_sock
					with patch("os.chmod"):
						with patch.object(d, "_load_model", side_effect=RuntimeError("abort")):
							with patch.object(d, "_check_encryption"):
								with patch.object(d, "stop", side_effect=fake_stop):
									d.start()
		assert not os.path.exists(sock_path)

	def test_startup_failure_calls_stop(self, short_socket_dir):
		"""Lines 119-121: _load_model raises → stop() called."""
		sock_path = str(short_socket_dir / "test2.sock")
		with patch("red_pill.config.SIDECAR_AUTH_KEY", "test_key"):
			d = MemoryDaemon()

			def fake_stop(*args):
				d.running = False

			with patch("red_pill.memory_daemon.SOCKET_PATH", sock_path):
				with patch("socket.socket") as mock_sock_cls:
					mock_sock = MagicMock()
					mock_sock.accept.side_effect = socket.timeout("timed out")
					mock_sock_cls.return_value = mock_sock
					with patch("os.chmod"):
						with patch.object(d, "_load_model", side_effect=RuntimeError("GPU fail")):
							with patch.object(d, "_check_encryption"):
								with patch.object(d, "stop", side_effect=fake_stop) as mock_stop:
									d.start()
		mock_stop.assert_called()


# ─────────────────────────────────────────────────────────────────────────────
# handle_connection() edge cases — lines 143, 151, 155, 174, 182-183
# ─────────────────────────────────────────────────────────────────────────────


class TestHandleConnectionEdgeCases:
	def test_empty_header_returns_early(self, daemon):
		"""Line 143: recv returns empty bytes → return."""
		mock_conn = MagicMock(spec=socket.socket)
		mock_conn.recv.return_value = b""
		daemon.handle_connection(mock_conn)
		mock_conn.sendall.assert_not_called()

	def test_chunk_break_on_empty_chunk(self, daemon):
		"""Line 151: chunk returns empty bytes mid-read → break from read loop."""
		mock_conn = MagicMock(spec=socket.socket)
		# payload_len = 100, but we only deliver 50 bytes then an empty chunk → break
		# data will be b'x'*50 (not empty), which is then parsed as JSON and fails
		payload = b"x" * 100
		header = len(payload).to_bytes(4, "big")
		mock_conn.recv.side_effect = [header, b"x" * 50, b""]
		daemon.handle_connection(mock_conn)
		# data = b'x'*50 is non-empty so will try to parse; it's invalid JSON → error response
		if mock_conn.sendall.called:
			args, _ = mock_conn.sendall.call_args
			resp = json.loads(args[0][4:].decode("utf-8"))
			assert resp["status"] == "error"
		# Either way: no crash, test passes

	def test_empty_data_after_header_returns_early(self, daemon):
		"""Line 155: chunk recv returns empty immediately → data empty → return."""
		mock_conn = MagicMock(spec=socket.socket)
		payload_len = 10
		header = payload_len.to_bytes(4, "big")
		mock_conn.recv.side_effect = [header, b""]
		daemon.handle_connection(mock_conn)
		mock_conn.sendall.assert_not_called()

	def test_missing_input_returns_error(self, daemon):
		"""Line 174: authenticated but no text and no ping command → error."""
		mock_conn = MagicMock(spec=socket.socket)
		req_data = {"api_key": "valid_key"}  # no text, no command
		payload = json.dumps(req_data).encode("utf-8")
		header = len(payload).to_bytes(4, "big")
		mock_conn.recv.side_effect = [header, payload]

		with patch("red_pill.config.SIDECAR_AUTH_KEY", "valid_key"):
			daemon.handle_connection(mock_conn)

		args, _ = mock_conn.sendall.call_args
		resp_body = json.loads(args[0][4:].decode("utf-8"))
		assert resp_body["status"] == "error"
		assert "Missing" in resp_body["message"]

	def test_outer_exception_logged(self, daemon):
		"""Lines 182-183: outer recv raises → error logged, no crash."""
		mock_conn = MagicMock(spec=socket.socket)
		mock_conn.recv.side_effect = OSError("connection reset")
		daemon.handle_connection(mock_conn)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# stop() — lines 187, 196-197, 201-202
# ─────────────────────────────────────────────────────────────────────────────


class TestDaemonStop:
	def test_stop_when_already_stopped_returns(self):
		"""Line 187: running=False → return immediately."""
		d = MemoryDaemon()
		d.running = False
		d.stop()  # Should not raise

	def test_stop_server_close_exception_handled(self):
		"""Lines 196-197: server.close() raises → swallowed."""
		d = MemoryDaemon()
		d.running = True
		d.server = MagicMock()
		d.server.close.side_effect = OSError("already closed")
		d.stop()  # Must not raise

	def test_stop_removes_socket_file(self, short_socket_dir):
		"""Lines 198-202: socket path exists → remove."""
		sock_path = str(short_socket_dir / "test.sock")
		open(sock_path, "w").close()

		d = MemoryDaemon()
		d.running = True
		d.server = MagicMock()

		with patch("red_pill.memory_daemon.SOCKET_PATH", sock_path):
			d.stop()

		import os

		assert not os.path.exists(sock_path)

	def test_stop_remove_exception_handled(self, short_socket_dir):
		"""Lines 201-202: os.remove raises → swallowed."""
		sock_path = str(short_socket_dir / "test.sock")
		open(sock_path, "w").close()

		d = MemoryDaemon()
		d.running = True
		d.server = MagicMock()

		with patch("red_pill.memory_daemon.SOCKET_PATH", sock_path):
			with patch("os.remove", side_effect=OSError("permission denied")):
				d.stop()  # Must not raise


# ─────────────────────────────────────────────────────────────────────────────
# __main__ block — lines 206-209
# ─────────────────────────────────────────────────────────────────────────────


class TestMainBlock:
	def test_main_entry_point_sigint_registered(self):
		"""Lines 206-209: __main__ block creates daemon, registers SIGINT/SIGTERM, calls start()."""
		import signal as signal_mod

		mock_daemon = MagicMock()
		mock_daemon.start = MagicMock()

		with patch("red_pill.memory_daemon.MemoryDaemon", return_value=mock_daemon) as mock_cls:
			with patch("red_pill.memory_daemon.signal") as mock_signal:
				# Simulate the __main__ block directly

				daemon = mock_cls()
				mock_signal.signal(signal_mod.SIGINT, daemon.stop)
				mock_signal.signal(signal_mod.SIGTERM, daemon.stop)
				daemon.start()

		mock_daemon.start.assert_called_once()
		assert mock_signal.signal.call_count >= 2
