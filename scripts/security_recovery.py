import argparse
import hashlib
import os
import random
import sys

# Ensure we can import red_pill
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
import red_pill.config as cfg
from src.red_pill.memory import MemoryManager


def get_hash(text: str) -> str:
	return hashlib.sha256(text.encode()).hexdigest()


def run_recovery_handshake():
	manager = MemoryManager()

	# Check if a master hash exists
	points, _ = manager.client.scroll(
		collection_name="directive_memories", scroll_filter={"must": [{"key": "security_tier", "match": {"value": 2}}]}, limit=1
	)

	if not points:
		print("ERROR: No recovery engram found. This Bünker is in OPEN mode or CUSTOM mode.")
		return

	master_hash = points[0].payload.get("master_hash")

	print("\n--- [IDENTITY RECOVERY PROTOCOL (IRP) ACTIVATED] ---")
	print("Initiating Synaptic Handshake. You must prove your identity.")

	# Step 1: Password Check
	pwd = input("Enter Master Password: ")
	if get_hash(pwd) != master_hash:
		print("CRITICAL: Invalid password. Handshake terminated.")
		return

	# Step 2: Memory Questions (Synaptic Handshake)
	print("\nPassword verified. Challenging shared memories...")

	# Collect potential memories for questions
	collections = ["social_memories", "work_memories"]
	all_memories = []
	for col in collections:
		res, _ = manager.client.scroll(collection_name=col, limit=50, with_payload=True)
		for hit in res:
			content = hit.payload.get("content", "")
			if len(content) > 30 and not hit.payload.get("immune"):
				all_memories.append(content)

	if len(all_memories) < 10:
		print("WARNING: Not enough memories for a full handshake. Security threshold lowered.")
		num_questions = len(all_memories)
	else:
		num_questions = 10

	random.shuffle(all_memories)
	questions = all_memories[:num_questions]

	correct = 0
	for i, mem in enumerate(questions):
		# Create a "fill in the blanks" or simple check
		words = mem.split()
		if len(words) > 10:
			snippet = " ".join(words[: len(words) // 2])
			answer = " ".join(words[len(words) // 2 :])
			print(f"\nQuestion {i + 1}/{num_questions}: Complete this memory...")
			print(f'"{snippet} [...]"')
			user_ans = input("Your answer: ")

			# Simple fuzzy check (at least some words match)
			if any(word.lower() in user_ans.lower() for word in answer.split() if len(word) > 4):
				print("✓ Synapse verified.")
				correct += 1
			else:
				print("✗ Cognitive mismatch.")
		else:
			print(f"\nQuestion {i + 1}/{num_questions}: Do you recall this? (y/n)")
			print(f'"{mem}"')
			if input("> ").lower() == "y":
				correct += 1

	threshold = (num_questions * 8) // 10
	if correct >= threshold:
		print(f"\n[HANDSHAKE SUCCESSFUL] {correct}/{num_questions}")
		print(f"Bünker Access Restored. Qdrant API Key: {cfg.QDRANT_API_KEY}")
	else:
		print(f"\n[HANDSHAKE FAILED] {correct}/{num_questions}")
		print("Access denied. Agent entering Stasis Mode.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--handshake", action="store_true")
	args = parser.parse_args()

	if args.handshake:
		run_recovery_handshake()
	else:
		print("Red Pill Security Utility v5.0")
