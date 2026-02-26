import argparse
import os
import random
import sys

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Ensure we can import red_pill
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
import red_pill.config as cfg
from src.red_pill.memory import MemoryManager
from src.red_pill.utils.keystore import has_recovery_hash, load_recovery_hash


def run_recovery_handshake():
	manager = MemoryManager()

	# SEC-001: Check for IRP presence marker in Qdrant (no hash material stored there)
	points, _ = manager.client.scroll(
		collection_name="directive_memories",
		scroll_filter={"must": [{"key": "security_tier", "match": {"value": 2}}]},
		limit=1,
	)

	if not points:
		print("ERROR: No IRP marker found. This Bünker is in OPEN mode or CUSTOM mode.")
		return

	# SEC-001: Load hash from OS keystore, NOT from Qdrant
	if not has_recovery_hash():
		print(
			"CRITICAL: IRP marker exists in Qdrant but no recovery hash found in the OS keystore.\n"
			"The keystore file may have been deleted or moved. Check: ~/.config/red_pill/recovery.key"
		)
		return

	print("\n--- [IDENTITY RECOVERY PROTOCOL (IRP) ACTIVATED] ---")
	print("Initiating Synaptic Handshake. You must prove your identity.")

	# Step 1: Password Prove (Be Water: Support Argon2-id and SHA-256)
	pwd = input("Enter Master Password: ")
	try:
		argon2_hash = load_recovery_hash()
		if argon2_hash.startswith("$argon2"):
			ph = PasswordHasher()
			ph.verify(argon2_hash, pwd)
		else:
			import hashlib

			# Legacy/Agua check
			user_hash = hashlib.sha256(pwd.encode()).hexdigest()
			if user_hash != argon2_hash:
				raise VerifyMismatchError()
	except VerifyMismatchError:
		print("CRITICAL: Invalid password. Handshake terminated.")
		return
	except (VerificationError, InvalidHashError) as e:
		print(f"CRITICAL: Hash verification error: {e}")
		return
	except PermissionError as e:
		print(f"CRITICAL: Keystore access error: {e}")
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
