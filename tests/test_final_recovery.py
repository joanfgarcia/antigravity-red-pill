import os
import socket
from unittest.mock import MagicMock, patch

import pytest
from red_pill.skills.swarm_messaging import SwarmMessagingSkill
from red_pill.memory_daemon import MemoryDaemon


def test_swarm_messaging_error():
	"""Test error handling in SwarmMessagingSkill with correct init."""
	skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret="secret")
	# Mock open to fail
	with patch("builtins.open", side_effect=PermissionError("Denied")):
		# In SwarmMessagingSkill, if check_mailbox is called, it returns [] if not client
		result = skill.check_mailbox()
		assert result == []


def test_memory_daemon_stop_logic():
	"""Test that the daemon stops correctly on signal."""
	daemon = MemoryDaemon()
	daemon.running = True
	daemon.stop()
	assert daemon.running is False


def test_memory_daemon_start_non_blocking():
	"""Test daemon start with a mocked socket accept to prevent timeout."""
	daemon = MemoryDaemon()
	# Mock config to have a key
	with patch("red_pill.config.SIDECAR_AUTH_KEY", "test-key"):
		# Mock socket to not block
		mock_socket = MagicMock()
		# Return a mock connection and then raise timeout to exit the loop
		mock_socket.accept.side_effect = [(MagicMock(), ("127.0.0.1", 123)), socket.timeout()]
		# Mock bind to avoid file system interaction
		mock_socket.bind = MagicMock()
		
		with patch("socket.socket", return_value=mock_socket):
			with patch("os.remove"):
				with patch("os.chmod"):
					with patch("red_pill.heartbeat.LazarusPulse"):
						with patch("red_pill.memory.MemoryManager"):
							with patch("red_pill.soul.SoulManager"):
								def stop_next(*args):
									daemon.running = False
									# Valid header but no data to trigger error or just exit
									return (MagicMock(), ("127.0.0.1", 123))
								
								mock_socket.accept.side_effect = stop_next
								
								daemon.start()
								assert mock_socket.accept.call_count >= 1


def test_memory_daemon_handle_connection_error():
	"""Test connection handling error logic."""
	daemon = MemoryDaemon()
	mock_conn = MagicMock()
	# Return a header with length 4, then the data, then empty to trigger JSON error
	# "junk" is 4 bytes. Not valid JSON.
	mock_conn.recv.side_effect = [b"\x00\x00\x00\x04", b"junk"]
	daemon.handle_connection(mock_conn)
	assert mock_conn.sendall.call_count == 1 # Should respond with error for invalid JSON
