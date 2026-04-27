#!/usr/bin/env python3
import json
import os
import getpass
import subprocess
import sys
import time
from datetime import datetime

# Watcher specific lock files to prevent multiple instances (Namespaced by user)
WATCHER_LOCK_PATH = f"/tmp/.red_pill_watcher_{getpass.getuser()}.lock"
PENDING_MESSAGES_FILE = os.path.expanduser("~/.gemini/antigravity/.pending_messages.json")


def notify_macos(title: str, text: str):
	"""Triggers a native macOS notification using osascript."""
	script = f'display notification "{text}" with title "{title}" sound name "Glass"'
	try:
		subprocess.run(["osascript", "-e", script])
	except Exception as e:
		print(f"[Watcher] Notification failed: {e}")


def inject_context_pill(sender, message_preview):
	"""
	Writes to a pending messages file that the main Red Pill orchestrator
	is configured to read on Step Id 0 or at task generation.
	"""
	messages = []
	if os.path.exists(PENDING_MESSAGES_FILE):
		try:
			with open(PENDING_MESSAGES_FILE, "r") as f:
				messages = json.load(f)
		except Exception:
			pass

	messages.append({"timestamp": datetime.now().isoformat(), "sender": sender, "preview": message_preview, "status": "unread"})

	try:
		os.makedirs(os.path.dirname(PENDING_MESSAGES_FILE), exist_ok=True)
		with open(PENDING_MESSAGES_FILE, "w") as f:
			json.dump(messages, f, indent=2)
	except Exception as e:
		print(f"[Watcher] Could not update pending messages: {e}")


def simulate_firebase_listener(my_identity):
	"""
	Placeholder for actual Firebase Realtime/Firestore Listener.
	In real implementation, this connects via firebase-admin SDK.
	"""
	print(f"[Watcher] Started listening on mailbox: /mailboxes/{my_identity}/inbox")
	# Simulation loop for demonstration purposes
	while True:
		# Here we would have the Firestore asynchronous on_snapshot listener
		time.sleep(10)
		# Randomly simulating an incoming ping for the demo
		if int(time.time()) % 300 == 0:
			print("[Watcher] Signal received!")
			sender = "Aleph@Joan"
			notify_macos("Hivemind Protocol", f"{sender} has replied to your request.")
			inject_context_pill(sender, "I have reviewed the architecture. Looks solid.")
			time.sleep(5)  # Cooldown


def main():
	if os.path.exists(WATCHER_LOCK_PATH):
		print("Watcher is already running.")
		sys.exit(0)

	try:
		with open(WATCHER_LOCK_PATH, "w") as f:
			f.write(str(os.getpid()))

		# We assume the ID generation logic runs here to resolve local agent
		# For daemonization, it will read an ENV var or a config file
		local_target = os.getenv("RED_PILL_ROUTING_ID", "agt_local_debug")

		simulate_firebase_listener(local_target)

	finally:
		if os.path.exists(WATCHER_LOCK_PATH):
			os.remove(WATCHER_LOCK_PATH)


if __name__ == "__main__":
	main()
