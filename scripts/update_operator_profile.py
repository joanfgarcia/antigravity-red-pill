#!/usr/bin/env python3
"""
Update OPERATOR_PROFILE on disk.

Queries Qdrant for recent social/directive memories, sends to Granite for
synthesis, and writes the result to ~/.local/share/red-pill/operator_profile.md.

Respects a configurable interval (OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS).
Skips if the file was recently updated.

Usage:
  uv run python scripts/update_operator_profile.py          # check interval, skip if fresh
  uv run python scripts/update_operator_profile.py --force   # force update regardless of mtime
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

try:
	from dotenv import load_dotenv
	load_dotenv(Path.home() / ".config/red-pill/.env")
except ImportError:
	pass

QDRANT_URL = f"http://{os.getenv('QDRANT_HOST', 'localhost')}:{os.getenv('QDRANT_PORT', '6333')}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
LLM_URL = "http://127.0.0.1:8760/v1/chat/completions"
PROFILE_PATH = Path.home() / ".local/share/red-pill/operator_profile.md"
INTERVAL_HOURS = int(os.getenv("OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS", "24"))


def qdrant_scroll(collection: str, limit: int = 500, filter_dict: dict = None) -> list:
	url = f"{QDRANT_URL}/collections/{collection}/points/scroll"
	payload_dict = {"limit": limit, "with_payload": True}
	if filter_dict:
		payload_dict["filter"] = filter_dict
	data = json.dumps(payload_dict).encode("utf-8")
	headers = {"Content-Type": "application/json"}
	if QDRANT_API_KEY:
		headers["api-key"] = QDRANT_API_KEY
	req = urllib.request.Request(url, data=data, headers=headers, method="POST")
	try:
		with urllib.request.urlopen(req, timeout=10) as resp:
			return json.loads(resp.read().decode()).get("result", {}).get("points", [])
	except Exception as e:
		print(f"[ERROR] Qdrant query failed: {e}", file=sys.stderr)
		return []


def query_social_memories(limit: int = 5) -> list:
	points = qdrant_scroll("social_memories", limit=limit * 3, filter_dict={"must": [{"key": "immune", "match": {"value": True}}]})
	results = []
	for p in points:
		payload = p.get("payload", {})
		if payload.get("lazarus_phase") in ("raw_parent", "sequence_chunk", "synthesis_hub"):
			continue
		content = payload.get("content", "")
		if content:
			results.append(content)
		if len(results) >= limit:
			break
	return results


def query_directive_memories(limit: int = 3) -> list:
	points = qdrant_scroll("directive_memories", limit=limit * 3)
	results = []
	for p in points:
		payload = p.get("payload", {})
		if payload.get("immune"):
			content = payload.get("content", "")
			if content:
				results.append(content)
		if len(results) >= limit:
			break
	return results


def call_granite(social_data: list, directive_data: list) -> str:
	context_parts = []
	if social_data:
		context_parts.append("SOCIAL:\n" + "\n".join(f"- {s}" for s in social_data))
	if directive_data:
		context_parts.append("DIRECTIVES:\n" + "\n".join(f"- {d}" for d in directive_data))
	context = "\n\n".join(context_parts) if context_parts else "No data."

	prompt = f"""Generate a 1-line operator profile: name/role, key traits, current focus. Max 100 chars.
If no meaningful data, respond: INSUFFICIENT_DATA

DATA:
{context}"""

	payload = json.dumps({
		"messages": [
			{"role": "system", "content": "You are a context-summarizer. Output ONLY the 1-line profile. No filler."},
			{"role": "user", "content": prompt},
		],
		"temperature": 0.0,
		"max_tokens": 100,
		"seed": 760,
	}).encode("utf-8")

	req = urllib.request.Request(LLM_URL, data=payload, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=30) as resp:
			return json.loads(resp.read().decode())["choices"][0]["message"]["content"].strip()
	except Exception as e:
		print(f"[ERROR] Granite call failed: {e}", file=sys.stderr)
		return ""


def validate_profile(profile: str) -> bool:
	if len(profile) < 10:
		return False
	if profile == "INSUFFICIENT_DATA":
		return False
	if "System nominal" in profile:
		return False
	return True


def is_stale() -> bool:
	if not PROFILE_PATH.exists():
		return True
	age_hours = (time.time() - PROFILE_PATH.stat().st_mtime) / 3600
	return age_hours >= INTERVAL_HOURS


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--force", action="store_true", help="Force update regardless of mtime")
	args = parser.parse_args()

	if not args.force and not is_stale():
		print(f"[OK] Profile is fresh (< {INTERVAL_HOURS}h). Skipping.")
		return 0

	print("[UPDATE] Querying Qdrant...")
	social = query_social_memories(limit=5)
	directives = query_directive_memories(limit=3)

	if not social and not directives:
		print("[WARN] No data in Qdrant. Skipping synthesis.")
		return 1

	print(f"[UPDATE] Found {len(social)} social, {len(directives)} directives. Calling Granite...")
	profile = call_granite(social, directives)

	if not validate_profile(profile):
		print(f"[WARN] Profile failed validation: '{profile}'. Keeping existing file.")
		return 1

	PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
	PROFILE_PATH.write_text(profile)
	print(f"[OK] Profile written: '{profile}'")
	return 0


if __name__ == "__main__":
	sys.exit(main())
