import os
import sys
import time

import requests

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

import red_pill.config as cfg


def check_bunker_health():
	print("\n--- [BÜNKER HEALTH CHECK] ---")
	url = f"http://{cfg.QDRANT_HOST}:{cfg.QDRANT_PORT}"
	headers = {"api-key": cfg.QDRANT_API_KEY} if cfg.QDRANT_API_KEY else {}

	# 1. Connection check
	try:
		resp = requests.get(f"{url}/health", headers=headers, timeout=5)
		if resp.status_code == 401:
			print("❌ [FAIL] Unauthorized: Incorrect API Key.")
			return False
		resp.raise_for_status()
		print("✅ [OK] Qdrant Connection established.")
	except Exception as e:
		print(f"❌ [FAIL] Could not connect to Qdrant: {e}")
		return False

	# 2. Schema check (Wait for seed to be effective)
	try:
		from qdrant_client import QdrantClient

		client = QdrantClient(url=url, api_key=cfg.QDRANT_API_KEY)
		collections = client.get_collections().collections
		names = [c.name for c in collections]
		required = ["work_memories", "system_signals"]
		for req in required:
			if req not in names:
				print(f"❌ [FAIL] Collection '{req}' missing. Seed might have failed.")
				return False
		print(f"✅ [OK] Standard Collections found ({len(names)} total).")
	except Exception as e:
		print(f"❌ [FAIL] Schema verification failed: {e}")
		return False

	# 3. Read/Write test
	try:
		from qdrant_client.http import models

		test_id = 999999
		client.upsert(
			collection_name="system_signals",
			points=[
				models.PointStruct(id=test_id, vector=[0.1] * cfg.VECTOR_SIZE, payload={"test": "installation_verify", "timestamp": time.time()})
			],
		)
		# Verify read
		res = client.retrieve(collection_name="system_signals", ids=[test_id])
		if not res:
			print("❌ [FAIL] Read/Write test failed: Point not retrieved.")
			return False
		# Cleanup
		client.delete(collection_name="system_signals", points_selector=models.PointIdsList(points=[test_id]))
		print("✅ [OK] Bünker Read/Write operation successful.")
	except Exception as e:
		print(f"❌ [FAIL] Read/Write operation failed: {e}")
		return False

	print("\n[SUCCESS] Bünker Health is Optimal. Sovereignty Guaranteed.")
	return True


if __name__ == "__main__":
	if check_bunker_health():
		sys.exit(0)
	else:
		sys.exit(1)
