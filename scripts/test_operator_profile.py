#!/usr/bin/env python3
"""
Test: Granite OPERATOR_PROFILE synthesis
Query Qdrant → send to Granite → validate response.

Usage: uv run python scripts/test_operator_profile.py
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

# Load .env
try:
	from dotenv import load_dotenv

	load_dotenv(Path.home() / ".config/red-pill/.env")
except ImportError:
	pass

QDRANT_URL = f"http://{os.getenv('QDRANT_HOST', 'localhost')}:{os.getenv('QDRANT_PORT', '6333')}"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
LLM_URL = "http://127.0.0.1:8760/v1/chat/completions"


def qdrant_scroll(collection: str, limit: int = 500, filter_dict: dict = None) -> list:
	"""Query Qdrant collection via HTTP."""
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
			result = json.loads(resp.read().decode())
			return result.get("result", {}).get("points", [])
	except Exception as e:
		print(f"[ERROR] Qdrant query failed for {collection}: {e}")
		return []


def query_social_memories(limit: int = 5) -> list:
	"""Query social_memories (immune only, exclude lazarus phases)."""
	points = qdrant_scroll(
		"social_memories",
		limit=limit * 3,  # overfetch to account for filtering
		filter_dict={"must": [{"key": "immune", "match": {"value": True}}]},
	)
	results = []
	for p in points:
		payload = p.get("payload", {})
		lazarus = payload.get("lazarus_phase")
		if lazarus in ("raw_parent", "sequence_chunk", "synthesis_hub"):
			continue
		content = payload.get("content", "")
		if content:
			results.append(content)
		if len(results) >= limit:
			break
	return results


def query_directive_memories(limit: int = 3) -> list:
	"""Query directive_memories (immune only)."""
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
	"""Send data to Granite for operator profile synthesis."""
	context_parts = []
	if social_data:
		context_parts.append("SOCIAL MEMORIES:\n" + "\n".join(f"- {s}" for s in social_data))
	if directive_data:
		context_parts.append("DIRECTIVES:\n" + "\n".join(f"- {d}" for d in directive_data))

	context = "\n\n".join(context_parts) if context_parts else "No data available."

	prompt = f"""Based on the following data about the operator, generate a single-line operator profile summary.
Include: name (if found), role, key traits, and current focus.
Be concise (max 100 chars). If no meaningful data, respond with exactly: INSUFFICIENT_DATA

DATA:
{context}"""

	payload = json.dumps(
		{
			"messages": [
				{
					"role": "system",
					"content": "You are a context-summarization sub-routine. Summarize operator data into a single line. Be factual, not creative.",
				},
				{"role": "user", "content": prompt},
			],
			"temperature": 0.0,
			"max_tokens": 100,
			"seed": 760,
		}
	).encode("utf-8")

	headers = {"Content-Type": "application/json"}
	req = urllib.request.Request(LLM_URL, data=payload, headers=headers, method="POST")

	try:
		with urllib.request.urlopen(req, timeout=30) as resp:
			result = json.loads(resp.read().decode())
			return result["choices"][0]["message"]["content"].strip()
	except Exception as e:
		print(f"[ERROR] Granite call failed: {e}")
		return ""


def validate_profile(profile: str) -> dict:
	"""Validate the synthesized profile."""
	checks = {
		"length_ok": len(profile) >= 10,
		"not_template": "System nominal" not in profile and "Persona engaged" not in profile,
		"not_insufficient": profile != "INSUFFICIENT_DATA",
		"has_content": bool(profile.strip()),
	}
	checks["overall"] = all(checks.values())
	return checks


def main():
	print("=" * 60)
	print("  TEST: Granite OPERATOR_PROFILE Synthesis")
	print("=" * 60)

	# Step 1: Query Qdrant
	print("\n[1/4] Querying social_memories...")
	social = query_social_memories(limit=5)
	print(f"  Found: {len(social)} memories")
	for i, s in enumerate(social):
		print(f"  [{i + 1}] {s[:120]}...")

	print("\n[2/4] Querying directive_memories...")
	directives = query_directive_memories(limit=3)
	print(f"  Found: {len(directives)} directives")
	for i, d in enumerate(directives):
		print(f"  [{i + 1}] {d[:120]}...")

	if not social and not directives:
		print("\n[WARN] No data found in Qdrant. Cannot test synthesis.")
		sys.exit(1)

	# Step 2: Call Granite
	print("\n[3/4] Calling Granite for synthesis...")
	profile = call_granite(social, directives)
	print(f'  Response: "{profile}"')

	# Step 3: Validate
	print("\n[4/4] Validating response...")
	checks = validate_profile(profile)
	for check, passed in checks.items():
		status = "PASS" if passed else "FAIL"
		print(f"  [{status}] {check}")

	print("\n" + "=" * 60)
	if checks["overall"]:
		print("  RESULT: SUCCESS - Granite can synthesize operator profile")
	else:
		print("  RESULT: FAIL - Granite response did not pass validation")
	print("=" * 60)

	return 0 if checks["overall"] else 1


if __name__ == "__main__":
	sys.exit(main())
