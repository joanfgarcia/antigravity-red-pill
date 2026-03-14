import logging
import os
import sys

# Project root setup
sys.path.append(os.getcwd() + "/src")

# Environment setup
os.environ["MILVUS_ENABLED"] = "True"
os.environ["MILVUS_LITE_ENABLED"] = "True"
os.environ["MILVUS_LITE_PATH"] = "/tmp/lazarus_integration_test.db"
os.environ["LAZARUS_STATE_FILE"] = "/tmp/lazarus_int_state.json"

from pymilvus import Collection, utility

import red_pill.config as cfg
from red_pill.hive import HiveMind
from red_pill.swarm.lazarus import LazarusSync
from red_pill.swarm.transports.milvus_transport import MilvusTransport

logging.basicConfig(level=logging.INFO)


def test_full_resurrection():
	print("--- Testing Full Lazarus Resurrection (Phase 6.2) ---")

	community = "lazarus_test"
	agent_id = "Aleph@Joan"

	# 0. Cleanup
	if os.path.exists("/tmp/lazarus_integration_test.db"):
		os.remove("/tmp/lazarus_integration_test.db")
	if os.path.exists("/tmp/lazarus_int_state.json"):
		os.remove("/tmp/lazarus_int_state.json")

	# Force drop collection if it survives in memory/cache
	try:
		col_name = f"swarm_proposals_{community}"
		if utility.has_collection(col_name):
			utility.drop_collection(col_name)
	except Exception:
		pass

	# 1. Simulate Offline: Propose to Local Dock
	transport = MilvusTransport(community)
	sync = LazarusSync(community, agent_id)

	engram_data = {
		"content": "Tactical implementation of Phase 6: Lazarus Sync logic.",
		"vector": [0.3] * cfg.VECTOR_SIZE,
		"metadata": {"target_collection": "work_memories", "level": "technical"},
	}

	# Add Lamport Stamp
	prepared = sync.prepare_engram(engram_data["content"], engram_data["vector"], engram_data["metadata"])

	print("Agent is OFFLINE. Proposing locally...")
	if transport.propose_engram(prepared):
		print("SUCCESS: Engram cached in local dock.")
	else:
		print("FAIL: Failed to cache engram.")
		assert False

	# 2. Verify it's in the Dock (and PENDING)
	col_name = f"swarm_proposals_{community}"
	col = Collection(col_name)
	res = col.query(expr='status == "PENDING"', output_fields=["proposal_id", "content"])
	print(f"Local Dock status: {len(res)} engrams pending.")
	assert len(res) == 1

	# 3. Simulate Restoration of Connection
	# (In this test, the connection is always 'local lite', but we simulate the logic)
	print("Restoring connection to Hive Mind...")
	hive = HiveMind()
	if hive.connected:
		print("SUCCESS: Hive Mind connected.")
	else:
		print("FAIL: Hive Mind connection failed.")
		assert False

	# 4. Run Vacuum (The Resurrection)
	print("Running vacuum...")
	count = sync.vacuum()
	print(f"Lazarus Vacuum result: {count} engrams resurrected.")
	assert count == 1

	# 5. Verify it's in the Hive Mind (Global Sector)
	# HiveMind.transmit_experience adds to the collection name provided
	hive_col = "work_memories"
	if utility.has_collection(hive_col):
		hive_entries = Collection(hive_col).query(expr="pk >= 0", output_fields=["content", "source_agent"], limit=100)
		print(f"Hive Sector {hive_col} contains {len(hive_entries)} entries.")
		found = any("Phase 6: Lazarus" in e["content"] for e in hive_entries)
		if found:
			print("VERIFIED: Engram moved to Hive Mind.")
		else:
			print("FAIL: Engram not found in Hive.")
			assert False
	else:
		print(f"FAIL: Hive collection {hive_col} not created.")
		assert False

	# 6. Verify Local Dock is now CANONIZED
	res = col.query(expr='status == "CANONIZED"', output_fields=["proposal_id"])
	print(f"Local Dock status: {len(res)} engrams canonized.")
	assert len(res) == 1


if __name__ == "__main__":
	try:
		test_full_resurrection()
		print("\n--- PHASE 6.2 INTEGRATION TEST PASSED ---")
		sys.exit(0)
	except Exception as e:
		print(f"\n--- TEST FAILURE: {e} ---")
		sys.exit(1)
