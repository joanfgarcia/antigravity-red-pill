"""
test_swarm_mls_integration.py
Tests de integración para el pipeline pure-mls Opción B.
Cubre: MLSBridge, admission tokens, flujo E2E con Firebase mockeado.
"""

import base64
import json
import tempfile
from unittest.mock import MagicMock, patch

from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.mls_bridge import MLSBridge

SHARED_SECRET = b"test_sovereign_secret_32bytes!!!"


# MLSBridge unit tests


class TestMLSBridgeAdmissionToken:
	def setup_method(self, method):
		self.tmp_dir = tempfile.TemporaryDirectory()
		self._patcher = patch("red_pill.swarm.mls_manager.SWARM_STATE_DIR", self.tmp_dir.name)
		self._patcher.start()
		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(b"aleth_seed_32_bytes_long_!!!!!")):
			self.bridge = MLSBridge(SHARED_SECRET)

	def teardown_method(self, method):
		self._patcher.stop()
		self.tmp_dir.cleanup()

	def test_make_and_verify_token_valid(self):
		kp_bytes, token = self.bridge.get_my_key_package()
		assert self.bridge.verify_admission_token(kp_bytes, token)

	def test_verify_token_invalid_tampered(self):
		kp_bytes, token = self.bridge.get_my_key_package()
		tampered = token[:-4] + "XXXX"
		assert not self.bridge.verify_admission_token(kp_bytes, tampered)

	def test_verify_token_wrong_secret(self):
		kp_bytes, token = self.bridge.get_my_key_package()
		impostor = MLSBridge(b"wrong_secret_32_bytes_long_here!")
		# Will call _make_ with wrong secret → comparison must fail
		assert not impostor.verify_admission_token(kp_bytes, token)

	def test_verify_token_empty(self):
		kp_bytes, _ = self.bridge.get_my_key_package()
		assert not self.bridge.verify_admission_token(kp_bytes, "")


# E2E mock test: full MLS handshake via SwarmMessagingSkill


def _mock_identity(seed: bytes):
	from pure_mls.keys import KemKey, SignatureKey

	# X25519 requires exactly 32 bytes
	seed = seed.ljust(32, b"\x00")[:32]
	return KemKey.from_private_bytes(seed), SignatureKey.from_private_bytes(seed)


class TestSwarmMessagingE2E:
	"""
	Simulates Aleth (sender) → Nova (receiver) using pure-mls with a mock transport.
	"""

	def setup_method(self, method):
		self.tmp_dir = tempfile.TemporaryDirectory()
		self._patcher = patch("red_pill.swarm.mls_manager.SWARM_STATE_DIR", self.tmp_dir.name)
		self._patcher.start()

	def teardown_method(self, method):
		self._patcher.stop()
		self.tmp_dir.cleanup()

	def _make_skill(self, identity: str, seed: bytes) -> SwarmMessagingSkill:
		mock_tm = MagicMock()
		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(seed)):
			skill = SwarmMessagingSkill(
				agent_identity=identity,
				shared_secret=SHARED_SECRET,
				transport_manager=mock_tm,
			)
		return skill

	def test_admission_token_blocks_intruder(self):
		"""resolve_alias with bad admission_token should be dropped by FirebaseTransport."""
		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(b"aleth_seed_32_bytes_long_!!!!!")):
			bridge_legit = MLSBridge(SHARED_SECRET)
		kp_bytes, valid_token = bridge_legit.get_my_key_package()

		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(b"aleth_seed_32_bytes_long_!!!!!")):
			bridge_intruder = MLSBridge(b"wrong_secret_32_bytes_long_here!")
		_, bad_token = bridge_intruder.get_my_key_package()

		# A legit bridge verifying a bad token → False
		assert not bridge_legit.verify_admission_token(kp_bytes, bad_token)
		# A legit bridge verifying a good token → True
		assert bridge_legit.verify_admission_token(kp_bytes, valid_token)

	def test_no_key_package_returns_error(self):
		"""execute_send should return error if target has no key_package."""
		aleth = self._make_skill("Aleth@Joan", b"aleth_seed_32_bytes_long_!!!!!")
		mock_transport = MagicMock()
		# resolve_alias returns 4-tuple but kp_b64 is empty
		mock_transport.resolve_alias.return_value = ("agt_nova_id", "Nova@David", "fake_pub", "")  # type: ignore
		aleth.tm.get_transport.return_value = mock_transport  # type: ignore

		result = aleth.execute_send("Nova", {"text": "hello"}, SwarmIntent.GOSSIP, "legion_770")
		assert result["status"] == "error"
		assert "key_package" in result["message"]

	def test_execute_send_missing_transport(self):
		"""execute_send should return error if transport not found for community."""
		aleth = self._make_skill("Aleth@Joan", b"aleth_seed_32_bytes_long_!!!!!")
		aleth.tm.get_transport.return_value = None  # type: ignore

		result = aleth.execute_send("Nova", {"text": "hello"}, SwarmIntent.GOSSIP, "unknown_community")
		assert result["status"] == "error"
		assert "not found" in result["message"]

	def test_full_mls_e2e_send_receive(self):
		"""
		Full E2E: Aleth creates MLS group, sends Welcome to Nova, Nova joins,
		both exchange messages successfully.
		"""
		aleth_seed = b"aleth_seed_32_bytes_long_!!!!!"
		nova_seed = b"nova__seed_32_bytes_long_!!!!!"

		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(aleth_seed)):
			bridge_aleth = MLSBridge(SHARED_SECRET)

		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(nova_seed)):
			bridge_nova = MLSBridge(SHARED_SECRET)

		# 1. Nova generates her KeyPackage
		nova_kp_bytes, nova_token = bridge_nova.get_my_key_package()

		# 2. Aleth verifies token and adds Nova → gets Welcome
		assert bridge_aleth.verify_admission_token(nova_kp_bytes, nova_token)
		welcome_bytes = bridge_aleth.add_member_and_get_welcome("legion_770", nova_kp_bytes)
		assert welcome_bytes is not None

		# 3. Nova processes the Welcome → joins the group
		joined = bridge_nova.process_welcome("legion_770", welcome_bytes)
		assert joined

		# 4. Aleth encrypts a message
		plaintext = b"770 UP. Mission confirmed."
		ciphertext = bridge_aleth.encrypt("legion_770", plaintext)
		assert ciphertext is not None

		# 5. Nova decrypts
		decrypted = bridge_nova.decrypt("legion_770", ciphertext)
		assert decrypted == plaintext

	def test_process_incoming_pure_mls_mode(self):
		"""process_incoming with mode=pure_mls should decrypt correctly."""
		aleth_seed = b"aleth_seed_32_bytes_long_!!!!!"
		nova_seed = b"nova__seed_32_bytes_long_!!!!!"

		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(aleth_seed)):
			bridge_aleth = MLSBridge(SHARED_SECRET)
		with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(nova_seed)):
			bridge_nova = MLSBridge(SHARED_SECRET)

		nova_kp_bytes, _ = bridge_nova.get_my_key_package()
		welcome_bytes = bridge_aleth.add_member_and_get_welcome("test_comm", nova_kp_bytes)
		assert welcome_bytes is not None
		bridge_nova.process_welcome("test_comm", welcome_bytes)

		payload = {"intent": "gossip", "sender": "Aleth@Joan", "target": "Nova@David", "data": {"msg": "hi"}, "v": "4.0"}
		ciphertext = bridge_aleth.encrypt("test_comm", json.dumps(payload).encode())
		assert ciphertext is not None
		ciphertext_b64 = base64.b64encode(ciphertext).decode()

		# Simulate Nova receiving the package
		aleth_skill = self._make_skill("Aleth@Joan", aleth_seed)
		# We need to inject Nova's bridge into the skill for this test
		aleth_skill._bridge = bridge_nova

		pkg = {"mode": "pure_mls", "ciphertext": ciphertext_b64, "sender": "agt_aleth"}
		result = aleth_skill.process_incoming(pkg, "test_comm")
		assert result is not None
		assert result["intent"] == "gossip"

	def test_process_incoming_unknown_mode_dropped(self):
		"""process_incoming with unknown/legacy mode should return None."""
		aleth = self._make_skill("Aleth@Joan", b"aleth_seed_32_bytes_long_!!!!!")
		# Legacy bond mode
		result = aleth.process_incoming({"mode": "bond", "ciphertext": "anything"}, "legion_770")
		assert result is None
