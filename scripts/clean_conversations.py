#!/usr/bin/env python3
"""
clean_conversations.py — Soverign Digestion/Cleaning Script
Reads raw exported Antigravity history, breaks it apart into individual files,
and gently scrubs noise (B64 blobs, endless loops, OOM terminal dumps) to ensure
clean ingestion to the Bünker's long-term memory.
"""

import argparse
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleaner")


def gentle_scrub(text: str) -> str:
	"""
	Cleans severe noise that disrupts cognitive models and breaks vector DBs.
	"""
	if not isinstance(text, str):
		return str(text)

	original_length = len(text)

	# Remove ANSI escape sequences
	text = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)

	# Remove massive hex blobs/base64 strings (likely artifacts/binary noise)
	text = re.sub(r"[A-Za-z0-9+/=]{300,}", "[CONTENT_BLOB_REDACTED]", text)

	# Remove massive repeated blocks or progress bars
	text = re.sub(r"\[.*\] (DEBUG|TRACE|INFO) .*", "", text)

	# Truncate completely oversized texts (to prevent Pydantic/Qdrant crashing)
	# 50,000 is a safe chunk for plain text (Qdrant payload limit usually ~64KB per string)
	if len(text) > 40000:
		text = text[:40000] + "\n...[TRUNCATED_BY_BUNKER_DUE_TO_SIZE]..."

	# Log significant reductions
	if original_length > 20000 and len(text) < original_length * 0.9:
		logger.debug(f"Reduced noise blob from {original_length} to {len(text)} chars.")

	return text.strip()


def process_and_split(input_path: Path, output_dir: Path):
	output_dir.mkdir(parents=True, exist_ok=True)

	try:
		with open(input_path, "r", encoding="utf-8") as f:
			data = json.load(f)
	except Exception as e:
		logger.error(f"Failed to load {input_path}: {e}")
		return

	sessions = data if isinstance(data, list) else [data]
	logger.info(f"Loaded {len(sessions)} sessions from {input_path.name}. Splitting and scrubbing...")

	clean_count = 0
	total_messages_processed = 0

	for idx, session in enumerate(sessions):
		# Extract metadata
		session_id = session.get("cascade_id") or session.get("session_id") or f"session_{idx}"
		# We replace any filesystem-unsafe characters to avoid path traversal bugs
		safe_session_id = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)

		# Scrub messages
		messages = session.get("messages", [])
		clean_messages = []
		for msg in messages:
			cleaned_msg = msg.copy()
			if "content" in cleaned_msg and cleaned_msg["content"]:
				cleaned_msg["content"] = gentle_scrub(cleaned_msg["content"])
			clean_messages.append(cleaned_msg)

		session["messages"] = clean_messages
		total_messages_processed += len(clean_messages)

		# Output clean individual JSON
		out_file = output_dir / f"{safe_session_id}.json"
		with open(out_file, "w", encoding="utf-8") as f:
			json.dump(session, f, indent=2, ensure_ascii=False)

		clean_count += 1

	logger.info(f"✅ Success: Processed and split {clean_count} sessions ({total_messages_processed} messages) into {output_dir}")


def main():
	parser = argparse.ArgumentParser(description="Split and clean Antigravity JSON exports.")
	parser.add_argument("--input", type=str, required=True, help="Input JSON file with all sessions.")
	parser.add_argument("--outdir", type=str, required=True, help="Directory to save the cleaned individual JSON files.")
	args = parser.parse_args()

	input_path = Path(args.input)
	output_dir = Path(args.outdir)

	if not input_path.exists():
		logger.error(f"Input file not found: {input_path}")
		return

	process_and_split(input_path, output_dir)


if __name__ == "__main__":
	main()
