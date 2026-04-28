import json
import os
from unittest.mock import MagicMock, patch

from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.watcher import inject_context_pill, notify_macos


def test_swarm_messaging_execute_send():
	"""Cover execute_send in SwarmMessagingSkill v4.0 (pure-mls path)."""
	from unittest.mock import patch

	from red_pill.skills.swarm_messaging import SwarmMessagingSkill

	with patch("red_pill.skills.swarm_messaging.TransportManager") as mock_tm_class:
		with patch("red_pill.skills.swarm_messaging.MLSBridge") as mock_bridge_class:
			mock_tm = mock_tm_class.return_value
			mock_transport = MagicMock()
			mock_tm.get_transport.return_value = mock_transport
			mock_transport.send_package.return_value = True
			# Return a 4-tuple with a valid kp_b64
			mock_transport.resolve_alias.return_value = ("agt_test123", "Nova@Test", "fake_pub", "dmFsaWRfa2V5")
			mock_bridge = mock_bridge_class.return_value
			mock_bridge.has_group.return_value = False
			mock_bridge.add_member_and_get_welcome.return_value = b"fake_welcome"
			mock_bridge.encrypt.return_value = b"fake_ciphertext"
			skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret=os.urandom(32), transport_manager=mock_tm)
			result = skill.execute_send("Nova@Test", {"code": "print(1)"}, SwarmIntent.LGTM_APPROVED)
			assert result["status"] == "dispatched"


def test_swarm_messaging_process_incoming():
	"""Cover process_incoming in SwarmMessagingSkill v4.0 — unknown mode is dropped."""
	from unittest.mock import patch

	with patch("red_pill.skills.swarm_messaging.TransportManager"):
		skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret=os.urandom(32))
	# Legacy 'bond' mode is unknown in v4.0 → dropped
	res = skill.process_incoming({"mode": "bond", "ciphertext": "abc"}, "legion_770")
	assert res is None
	# Unknown mode also dropped
	res = skill.process_incoming({"mode": "mls_asymmetric", "ciphertext": "abc"}, "legion_770")
	assert res is None


def test_watcher_inject_context_pill_append(tmp_path):
	"""Cover the line where we append to existing pending messages."""
	test_file = tmp_path / "pending.json"
	initial_data = [{"sender": "old", "preview": "old", "timestamp": 0}]
	test_file.write_text(json.dumps(initial_data))
	with patch("red_pill.swarm.watcher.PENDING_MESSAGES_FILE", str(test_file)):
		inject_context_pill("new_sender", "new_msg")
		with open(test_file, "r") as f:
			data = json.load(f)
			assert len(data) == 2
			assert data[1]["sender"] == "new_sender"


def test_watcher_notify_macos_no_display():
	"""Cover notify_macos when message is short (no display) or other branches."""
	with patch("subprocess.run") as mock_run:
		notify_macos("T", "M")
		assert mock_run.call_count == 1
