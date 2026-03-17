import logging
import os
import sys

# Project root setup
sys.path.append(os.getcwd() + "/src")

# Environment setup
os.environ["MILVUS_ENABLED"] = "True"
os.environ["MILVUS_LITE_ENABLED"] = "True"
os.environ["MILVUS_LITE_PATH"] = "/tmp/milvus_notary_test.db"

from pymilvus import Collection

import red_pill.config as cfg
from red_pill.swarm.crypto import SwarmCrypto
from red_pill.swarm.notary import NotaryOffice

logging.basicConfig(level=logging.INFO)


def test_peer_notary():
	print("--- Testing Peer Notary (Phase 5.2) ---")

	community = "consensus_test"

	# 1. Setup 3 Agent Identities
	agents = []
	names = ["Aleph", "Nova", "Sam"]
	for name in names:
		identity = SwarmCrypto.generate_unified_identity()
		office = NotaryOffice(community, identity["seed"], name)
		agents.append({"name": name, "seed": identity["seed"], "ed_pub": identity["ed25519_pub"], "office": office})
	print(f"SUCCESS: Generated {len(agents)} unified identities.")

	# 2. Aleph proposes an engram
	proposal_content = "The swarm protocol v3.5 is the foundation of digital sovereignty."
	dummy_vector = [0.1] * cfg.VECTOR_SIZE

	print(f"{agents[0]['name']} is proposing a new engram...")
	if agents[0]["office"].propose_knowledge(proposal_content, dummy_vector, {"source": "manual_input"}):
		print("SUCCESS: Engram proposed.")
	else:
		print("FAIL: Proposal failed.")
		assert False

	# 3. Retrieve Proposal from Ledger
	col_name = f"swarm_proposals_{community}"
	col = Collection(col_name)
	res = col.query(expr="proposal_id != ''", output_fields=["proposal_id", "content", "signatures", "vector", "metadata"], limit=10)

	if not res:
		print("FAIL: Proposal not found in ledger.")
		assert False

	proposal = res[0]
	proposal_id = proposal["proposal_id"]
	print(f"Found proposal: {proposal_id[:8]} -> '{proposal['content'][:20]}...'")

	# 4. Peer Auditing and Signing (Quorum 2/3)
	for agent in agents:
		print(f"Agent {agent['name']} is auditing and signing...")
		if agent["office"].audit_and_sign(proposal):
			print(f"SUCCESS: {agent['name']} signed.")
		else:
			print(f"FAIL: {agent['name']} failed to sign.")
			assert False

	# 5. Verify Signatures manually (Verification logic check)
	# Refresh proposal data
	print(f"Refreshing proposal data for ID: {proposal_id}")
	res = col.query(expr=f'proposal_id == "{proposal_id}"', output_fields=["signatures", "proposal_id", "vector", "metadata", "content"], limit=10)
	if not res:
		print("DEBUG: No proposal found by ID. Listing all existing proposals:")
		all_res = col.query(expr="pk >= 0", output_fields=["proposal_id"], limit=10)
		print(f"Total proposals in ledger: {len(all_res)}")
		for r in all_res:
			print(f" - {r['proposal_id']}")
		assert False

	signatures = res[0]["signatures"]
	print(f"Ledger contains {len(signatures)} signatures.")

	from base64 import b64decode

	for sig_entry in signatures:
		agent_name = sig_entry["agent"]
		sig_bytes = b64decode(sig_entry["sig"])

		# Find agent's public key
		target_agent = next(a for a in agents if a["name"] == agent_name)

		if SwarmCrypto.verify_notary(target_agent["ed_pub"], proposal_content.encode("utf-8"), sig_bytes):
			print(f"VERIFIED: Signature from {agent_name} is valid.")
		else:
			print(f"FAILED: Signature from {agent_name} is INVALID.")
			assert False

	# 6. Check Consensus and Promote
	final_proposal = res[0]
	if agents[0]["office"].check_consensus(final_proposal, quorum=2):
		print("QUORUM REACHED (2/3).")
		if agents[0]["office"].promote_to_hive(final_proposal):
			print("SUCCESS: Engram promoted to Canonical Hive.")
		else:
			print("FAIL: Promotion failed.")
			assert False
	else:
		print("FAIL: Consensus not reached.")
		assert False

	res = col.query(expr=f'proposal_id == "{proposal_id}"', output_fields=["signatures"])
	print(f"Quorum check: {len(res[0]['signatures'])} signatures found.")
	assert len(res[0]["signatures"]) >= 2


if __name__ == "__main__":
	# Cleanup previous DB
	if os.path.exists("/tmp/milvus_notary_test.db"):
		os.remove("/tmp/milvus_notary_test.db")

	try:
		test_peer_notary()
		print("\n--- ALL PEER NOTARY TESTS PASSED ---")
		sys.exit(0)
	except Exception as e:
		print(f"\n--- TEST FAILURE: {e} ---")
		sys.exit(1)
