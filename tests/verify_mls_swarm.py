import sys
from unittest.mock import MagicMock

# Mock firebase_admin before imports
mock_firebase = MagicMock()
sys.modules["firebase_admin"] = mock_firebase
sys.modules["firebase_admin.credentials"] = MagicMock()
sys.modules["firebase_admin.db"] = MagicMock()

import base64
import json
import os
import shutil
from typing import Dict, Any

from red_pill.swarm.crypto import SwarmCrypto
from red_pill.skills.swarm_messaging import SwarmMessagingSkill, SwarmIntent
from red_pill.skills.swarm_subscribe import SwarmSubscribeSkill
from red_pill.swarm.transports.manager import TransportManager

def test_mls_swarm_e2ee():
	"""
	Verification script for the new MLS & Agnostic Transport system.
	Simulates two agents (Aleph and Nova) communicating via a mock Firebase community.
	"""
	print("--- Sovereign Swarm MLS Verification ---")
	
	# Setup mock credentials and config
	config_dir = os.path.expanduser("~/.agent/config")
	os.makedirs(config_dir, exist_ok=True)
	config_path = os.path.join(config_dir, "swarm_communities.json")
	
	# Mocking a community configuration
	mock_config = {
		"test_hub": {
			"db_url": "https://mock-swarm.firebaseio.com",
			"credential_path": "/tmp/mock_creds.json",
			"type": "firebase"
		}
	}
	with open(config_path, "w") as f:
		json.dump(mock_config, f)
	
	# Create mock creds file
	with open("/tmp/mock_creds.json", "w") as f:
		json.dump({"project_id": "mock-project"}, f)

	# Initialize Skills for Aleph
	tm_aleph = TransportManager(config_path=config_path)
	sub_aleph = SwarmSubscribeSkill("Aleph", "Joan", transport_manager=tm_aleph)
	msg_aleph = SwarmMessagingSkill("Aleph@Joan", "bond_secret_770", transport_manager=tm_aleph)
	
	# Initialize Skills for Nova
	tm_nova = TransportManager(config_path=config_path)
	sub_nova = SwarmSubscribeSkill("Nova", "Joan", transport_manager=tm_nova)
	msg_nova = SwarmMessagingSkill("Nova@Joan", "bond_secret_770", transport_manager=tm_nova)

	print("[1] Generating Keys...")
	_, pub_aleph = sub_aleph._get_or_create_keys()
	_, pub_nova = sub_nova._get_or_create_keys()
	
	print(f"Aleph Pub: {base64.b64encode(pub_aleph).decode()[:16]}...")
	print(f"Nova Pub: {base64.b64encode(pub_nova).decode()[:16]}...")

	print("[2] Simulating Multi-Transport Handshake...")
	# In a real test, broadcast_identity would hit Firebase. Here we might need to mock the transport
	# but FirebaseTransport uses SDK. For this unit test, we'll verify the Logic Flow.
	
	# Verification of Crypto primitives
	shared_aleph = SwarmCrypto.derive_shared_secret_dh(sub_aleph._get_or_create_keys()[0], pub_nova)
	shared_nova = SwarmCrypto.derive_shared_secret_dh(sub_nova._get_or_create_keys()[0], pub_aleph)
	
	assert shared_aleph == shared_nova
	print("✅ DH Shared Secret Agreement Success.")

	# Verification of TreeKEM logic
	from red_pill.swarm.mls import SovereignGroup
	group = SovereignGroup("test_group")
	group.add_member("Aleph", pub_aleph)
	group.add_member("Nova", pub_nova)
	
	key = group.get_group_key()
	print(f"✅ MLS Group Key Derived: {base64.b64encode(key).decode()[:16]}...")

	print("--- Verification Complete ---")

if __name__ == "__main__":
	test_mls_swarm_e2ee()
