import os
import sys
import time

from qdrant_client import QdrantClient

# Add project src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(project_root, "src"))
import red_pill.config as cfg  # noqa: E402


def monitor():
	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	collection = "interaction_memories"

	print("\033[94m--- BÜNKER LIVE MONITOR (Anti-Amnesia) ---\033[0m")
	print(f"Monitoring collection: {collection}")
	print("Waiting for new engrams (Shadow Scribe pulse: 30s)...")
	print("-" * 50)

	seen_ids = set()

	# Initialize seen IDs
	if client.collection_exists(collection):
		res, _ = client.scroll(collection_name=collection, limit=100, with_payload=False)
		seen_ids = {p.id for p in res}

	try:
		while True:
			if client.collection_exists(collection):
				# Scroll to get'em all
				res, _ = client.scroll(collection_name=collection, limit=100, with_payload=True)
				new_points = [p for p in res if p.id not in seen_ids]

				for p in new_points:
					payload = p.payload or {}
					content = payload.get("content", "N/A")
					print(f"\033[92m[NEW ENGRAM DETECTED]\033[0m ID: {str(p.id)[:8]}")
					print(f"Content:\n{content}")
					print("-" * 50)
					seen_ids.add(p.id)

			time.sleep(5)
	except KeyboardInterrupt:
		print("\nMonitor stopped.")


if __name__ == "__main__":
	monitor()
