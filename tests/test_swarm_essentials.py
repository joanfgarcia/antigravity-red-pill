import json
import os
from unittest.mock import patch

from red_pill.swarm.messaging import AgentIdentity
from red_pill.swarm.watcher import inject_context_pill, notify_macos


def test_generate_agent_id():
	assert AgentIdentity.generate_agent_id("nova", "david") == "Nova@David"
	assert AgentIdentity.generate_agent_id("aleph", "joan") == "Aleph@Joan"


def test_resolve_local_identity():
	with patch.dict(os.environ, {"AGENT_TRUE_NAME": "Aleth", "OPERATOR_TRUE_NAME": "Joan"}):
		identity = AgentIdentity.resolve_local_identity()
		assert identity["agent_name"] == "Aleth"
		assert identity["operator_name"] == "Joan"


@patch("subprocess.run")
def test_notify_macos(mock_run):
	notify_macos("Title", "Text")
	assert mock_run.called
	args = mock_run.call_args[0][0]
	assert 'display notification "Text" with title "Title"' in args[2]


def test_inject_context_pill():
	test_file = "/tmp/.test_pending_messages.json"
	if os.path.exists(test_file):
		os.remove(test_file)
	with patch("red_pill.swarm.watcher.PENDING_MESSAGES_FILE", test_file):
		inject_context_pill("Sender", "Message")
		assert os.path.exists(test_file)
		with open(test_file, "r") as f:
			data = json.load(f)
			assert len(data) == 1
			assert data[0]["sender"] == "Sender"
			assert data[0]["preview"] == "Message"
		inject_context_pill("Sender2", "Message2")
		with open(test_file, "r") as f:
			data = json.load(f)
			assert len(data) == 2
			assert data[1]["sender"] == "Sender2"
	if os.path.exists(test_file):
		os.remove(test_file)


@patch("time.sleep", side_effect=[None, InterruptedError])
@patch("red_pill.swarm.watcher.notify_macos")
@patch("red_pill.swarm.watcher.inject_context_pill")
def test_simulate_firebase_listener_interrupted(mock_inject, mock_notify, mock_sleep):
	from red_pill.swarm.watcher import simulate_firebase_listener

	with patch("time.time", return_value=300):
		try:
			simulate_firebase_listener("test_id")
		except InterruptedError:
			pass
		assert mock_notify.called
		assert mock_inject.called
