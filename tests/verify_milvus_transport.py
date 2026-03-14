import logging
import os
import sys

# Ensure project root is in path
sys.path.append(os.getcwd() + "/src")

# Configure environment for Milvus-Lite testing
os.environ["MILVUS_ENABLED"] = "True"
os.environ["MILVUS_LITE_ENABLED"] = "True"
os.environ["MILVUS_LITE_PATH"] = "/tmp/milvus_test.db"

from red_pill.swarm.transports.milvus_transport import MilvusTransport

# Setup logging to see what's happening
logging.basicConfig(level=logging.INFO)


def test_milvus_transport():
	print("--- Testing MilvusTransport (Consensus Ledger Mode) ---")

	community = "test_community"
	transport = MilvusTransport(community)

	if not transport.hive.connected:
		print("FAIL: Could not connect to Milvus-Lite")
		return False

	print("SUCCESS: Connected to Milvus-Lite")

	agent_id = "test_agent_alpha"
	metadata = {"alias": "Alpha", "public_key": "X25519_FAKE_PUB_KEY", "communities": [community]}

	# 1. Broadcast Identity
	print(f"Broadcasting identity for {agent_id}...")
	if transport.broadcast_identity(agent_id, metadata):
		print("SUCCESS: Identity broadcasted")
	else:
		print("FAIL: Identity broadcast failed")
		return False

	# 2. Lookup Public Key
	print("Looking up public key for 'Alpha'...")
	pub_key = transport.lookup_public_key("Alpha")
	if pub_key == metadata["public_key"]:
		print(f"SUCCESS: Found public key: {pub_key}")
	else:
		print(f"FAIL: Public key lookup failed. Found: {pub_key}")
		return False

	# 3. Send Package
	package = {"sender_id": "test_agent_beta", "content": "Hello from the Hive!", "type": "test"}
	print(f"Sending package to {agent_id}...")
	if transport.send_package(agent_id, package):
		print("SUCCESS: Package sent")
	else:
		print("FAIL: Package send failed")
		return False

	# 4. Poll Mailbox
	print(f"Polling mailbox for {agent_id}...")
	messages = transport.poll_mailbox(agent_id)
	if len(messages) == 1 and messages[0]["content"] == package["content"]:
		print(f"SUCCESS: Received 1 message: {messages[0]['content']}")
	else:
		print(f"FAIL: No messages or unexpected content: {messages}")
		return False

	# 5. Verify destructive read
	print("Verifying destructive read (polling again)...")
	messages_again = transport.poll_mailbox(agent_id)
	if len(messages_again) == 0:
		print("SUCCESS: Mailbox cleared after read")
	else:
		print(f"FAIL: Mailbox not cleared: {len(messages_again)} messages remaining")
		return False

	return True


if __name__ == "__main__":
	if test_milvus_transport():
		print("\n--- ALL MILVUS TRANSPORT TESTS PASSED ---")
		sys.exit(0)
	else:
		print("\n--- TEST FAILURE ---")
		sys.exit(1)
