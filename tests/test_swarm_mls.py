import base64
from unittest.mock import MagicMock

from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.crypto import SwarmCrypto


def test_swarm_mls_encryption_flow(monkeypatch):
	# Test E2E asymmetric encryption flow for Swarm
	sender_id = SwarmCrypto.generate_unified_identity()
	receiver_id = SwarmCrypto.generate_unified_identity()

	def mock_get_private_key(self):
		return sender_id["seed"]

	monkeypatch.setattr(SwarmMessagingSkill, "_get_local_private_key", mock_get_private_key)

	mock_transport = MagicMock()
	remote_pub_b64 = base64.b64encode(receiver_id["x25519_pub"]).decode("utf-8")
	mock_transport.resolve_alias.return_value = ("agt_receiver", "Receiver@Node", remote_pub_b64)
	mock_transport.send_package.return_value = True

	mock_tm = MagicMock()
	mock_tm.get_transport.return_value = mock_transport

	skill = SwarmMessagingSkill("Sender@Node", "dummy_shared_secret", transport_manager=mock_tm)

	res = skill.execute_send("Receiver", {"hello": "mls"}, SwarmIntent.GOSSIP, "test_comm")
	assert res["status"] == "dispatched"

	mock_transport.send_package.assert_called_once()
	args, _ = mock_transport.send_package.call_args
	pkg = args[1]

	assert pkg["mode"] == "mls_asymmetric"
	assert "ciphertext" in pkg
	assert pkg["sender"] == "Sender@Node"

	# Receiving side
	receiver_skill = SwarmMessagingSkill("Receiver@Node", "dummy_shared_secret", transport_manager=mock_tm)

	def mock_get_private_key_receiver(self):
		return receiver_id["seed"]

	monkeypatch.setattr(SwarmMessagingSkill, "_get_local_private_key", mock_get_private_key_receiver)

	sender_pub_b64 = base64.b64encode(sender_id["x25519_pub"]).decode("utf-8")
	mock_transport.lookup_public_key.return_value = sender_pub_b64

	decrypted = receiver_skill.process_incoming(pkg, mock_transport)
	assert decrypted is not None
	assert decrypted["data"]["hello"] == "mls"
	assert decrypted["intent"] == "gossip"
	assert decrypted["target"] == "Receiver@Node"
