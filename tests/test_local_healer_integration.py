import json
import os
from unittest.mock import MagicMock, patch

from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.watcher import inject_context_pill, notify_macos


def test_swarm_messaging_execute_send():
	"""Cover execute_send in SwarmMessagingSkill."""
	with patch("red_pill.skills.swarm_messaging.TransportManager") as mock_tm_class:
		mock_tm = mock_tm_class.return_value
		mock_transport = MagicMock()
		mock_tm.get_transport.return_value = mock_transport
		mock_transport.send_package.return_value = True
		mock_transport.resolve_alias.return_value = ("agt_test123", "Nova@Test", None)
		mock_transport.lookup_public_key.return_value = None
		with patch("red_pill.skills.swarm_messaging.SwarmCrypto") as mock_crypto:
			mock_crypto.encrypt_payload.return_value = {"ciphertext": "fake", "nonce": "fake"}
			skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret=os.urandom(32), transport_manager=mock_tm)
			result = skill.execute_send("Nova@Test", {"code": "print(1)"}, SwarmIntent.LGTM_APPROVED)
			assert result["status"] == "dispatched"


def test_swarm_messaging_process_incoming():
	"""Cover process_incoming in SwarmMessagingSkill."""
	with patch("red_pill.skills.swarm_messaging.TransportManager"):
		skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret=os.urandom(32))
	with patch("red_pill.skills.swarm_messaging.SwarmCrypto") as mock_crypto:
		mock_crypto.decrypt_payload.return_value = {"intent": "lgtm_approved", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res["intent"] == SwarmIntent.LGTM_APPROVED.value  # type: ignore
		mock_crypto.decrypt_payload.return_value = {"intent": "change_requested", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res["intent"] == SwarmIntent.CHANGE_REQUESTED.value  # type: ignore
		mock_crypto.decrypt_payload.return_value = {"intent": "gossip", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res["intent"] == "gossip"  # type: ignore


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
