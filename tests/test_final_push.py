import os
import json
from unittest.mock import MagicMock, patch

import pytest
from red_pill.skills.swarm_messaging import SwarmMessagingSkill, SwarmIntent
from red_pill.swarm.watcher import notify_macos, inject_context_pill


def test_swarm_messaging_execute_send():
	"""Cover execute_send in SwarmMessagingSkill."""
	skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret="secret")
	result = skill.execute_send("Nova@Test", {"code": "print(1)"}, SwarmIntent.LGTM_APPROVED)
	assert result["status"] == "dispatched"


def test_swarm_messaging_process_incoming():
	"""Cover process_incoming in SwarmMessagingSkill."""
	skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret="secret")
	
	# Mock crypto to return different intents
	with patch("red_pill.swarm.crypto.SwarmCrypto.decrypt_payload") as mock_decrypt:
		mock_decrypt.return_value = {"intent": "lgtm_approved", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res == "auto_applied"
		
		mock_decrypt.return_value = {"intent": "change_requested", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res == "human_review_required"
		
		mock_decrypt.return_value = {"intent": "gossip", "sender": "Nova@Test"}
		res = skill.process_incoming({})
		assert res == "processed"


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
	# The current code always uses 'display notification' if message is provided.
	# But let's verify subprocess call count.
	with patch("subprocess.run") as mock_run:
		notify_macos("T", "M")
		assert mock_run.call_count == 1
