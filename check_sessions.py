import os

from red_pill.memory import MemoryManager

mem = MemoryManager()

limit = 10000
offset = None
all_points = []
while True:
	response = mem.client.scroll(collection_name="archive_memories", limit=1000, offset=offset, with_payload=["session_id"])
	points, offset = response
	all_points.extend(points)
	if offset is None:
		break

sessions = set(p.payload.get("session_id") for p in all_points if p.payload and "session_id" in p.payload)
print(f"Total points: {len(all_points)}")
print(f"Unique sessions in Qdrant: {len(sessions)}")


pb_dir = os.path.expanduser("~/.gemini/antigravity/conversations")
pb_files = [f.split(".")[0] for f in os.listdir(pb_dir) if f.endswith(".pb")]
print(f"Total .pb files: {len(pb_files)}")

missing_in_db = set(pb_files) - sessions
print(f"Missing in Qdrant: {len(missing_in_db)}")
if missing_in_db:
	print(list(missing_in_db)[:10])
