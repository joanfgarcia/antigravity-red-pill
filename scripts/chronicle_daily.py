#!/usr/bin/env python3
"""
chronicle_daily.py — Autonomous Chronicle Ingestion Pipeline

Automates the full chronicle ritual for unprocessed conversations:
  decrypt → ingest → distill → refine

Designed to run as a systemd --user oneshot service (daily, Persistent=true).
If the system was suspended at scheduled time, runs on next wake/boot.

Usage:
	uv run python scripts/chronicle_daily.py              # default: yesterday's conversations
	uv run python scripts/chronicle_daily.py --all       # all unprocessed conversations
	uv run python scripts/chronicle_daily.py --dry-run   # show what would be processed
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("chronicle_daily")

# ── Paths ────────────────────────────────────────────────────────────────────
CONVERSATIONS_DIR = Path.home() / ".gemini/antigravity/conversations"
PROCESSED_LOG = Path.home() / ".agent/chronicle_processed.json"
WORK_DIR = Path("/tmp/chronicle_today")
SCRIPTS_DIR = Path(__file__).parent


def _load_processed() -> dict:
	"""Load the set of already-processed session IDs."""
	if PROCESSED_LOG.exists():
		try:
			return json.loads(PROCESSED_LOG.read_text())
		except Exception:
			pass
	return {"processed": {}, "last_run": None, "stats": {"total_ingested": 0, "total_sessions": 0}}


def _save_processed(state: dict) -> None:
	PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
	PROCESSED_LOG.write_text(json.dumps(state, indent=2))


def _inject_pain_signal(title: str, details: str, severity: float = 8.0) -> None:
	"""Inject a pain signal into signal_memories so the Cortex is notified."""
	try:
		from red_pill.memory import MemoryManager

		mem = MemoryManager()
		mem.add_memory(
			collection="signal_memories",
			text=f"[PAIN] {title}: {details}",
			metadata={
				"title": title,
				"details": details,
				"severity": severity,
				"source": "chronicle_daily",
				"timestamp": datetime.now().isoformat(),
			},
			importance=severity,
		)
		logger.warning(f"Pain signal injected: {title}")
	except Exception as e:
		logger.error(f"Could not inject pain signal: {e}")


def _get_antigravity_key() -> str | None:
	"""Read ANTIGRAVITY_KEY from environment (loaded via .env by the caller)."""
	import os

	from dotenv import load_dotenv

	load_dotenv()
	return os.environ.get("ANTIGRAVITY_KEY")


def _find_pending(state: dict, only_yesterday: bool) -> list[Path]:
	"""Return .pb files not yet processed, optionally filtered to last 48h."""
	if not CONVERSATIONS_DIR.exists():
		logger.error(f"Conversations dir not found: {CONVERSATIONS_DIR}")
		return []

	cutoff = datetime.now() - timedelta(hours=48) if only_yesterday else None
	pending = []
	for pb in sorted(CONVERSATIONS_DIR.glob("*.pb")):
		session_id = pb.stem
		if session_id in state["processed"]:
			continue
		if cutoff:
			mtime = datetime.fromtimestamp(pb.stat().st_mtime)
			if mtime < cutoff:
				continue
		pending.append(pb)
	return pending


def _run(cmd: list[str], step: str) -> bool:
	"""Run a subprocess step, return True on success."""
	logger.info(f"[{step}] Running: {' '.join(cmd)}")
	result = subprocess.run(cmd, capture_output=False)
	if result.returncode != 0:
		logger.error(f"[{step}] FAILED (exit {result.returncode})")
		return False
	logger.info(f"[{step}] Done ✓")
	return True


def _llm_available() -> bool:
	"""Quick check if the local LLM endpoint responds."""
	import os
	import urllib.request

	url = os.environ.get("MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
	# Just check the base URL
	base = url.rsplit("/", 2)[0]
	try:
		urllib.request.urlopen(base, timeout=3)
		return True
	except Exception:
		return False


def main() -> None:
	parser = argparse.ArgumentParser(description="Autonomous Chronicle Ingestion Pipeline")
	parser.add_argument("--all", action="store_true", help="Process all unprocessed conversations (not just yesterday's)")
	parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without doing anything")
	args = parser.parse_args()

	# ── Preflight: key ────────────────────────────────────────────────────────
	key = _get_antigravity_key()
	if not key:
		msg = (
			"ANTIGRAVITY_KEY not set. Chronicle pipeline cannot decrypt conversations.\n"
			"  → Set it in .env: ANTIGRAVITY_KEY=<base64_key>\n"
			"  → Recovery guide: docs/TECHNICAL/ANTIGRAVITY_KEY_RECOVERY.md"
		)
		logger.error(msg)
		_inject_pain_signal(
			title="chronicle_daily: ANTIGRAVITY_KEY missing",
			details="The automated chronicle pipeline could not run because ANTIGRAVITY_KEY is not set in .env. See docs/TECHNICAL/ANTIGRAVITY_KEY_RECOVERY.md.",
			severity=8.5,
		)
		sys.exit(1)

	# ── Load state ────────────────────────────────────────────────────────────
	state = _load_processed()
	only_yesterday = not args.all
	pending = _find_pending(state, only_yesterday)

	if not pending:
		logger.info("No pending conversations to process. All up to date.")
		state["last_run"] = datetime.now().isoformat()
		_save_processed(state)
		return

	logger.info(f"Found {len(pending)} pending conversation(s) to process.")
	for p in pending:
		logger.info(f"  → {p.name}")

	if args.dry_run:
		logger.info("[DRY RUN] No changes made.")
		return

	# ── Prepare work dir ──────────────────────────────────────────────────────
	if WORK_DIR.exists():
		shutil.rmtree(WORK_DIR)
	WORK_DIR.mkdir(parents=True)

	try:
		uv = ["uv", "run", "python"]

		# ── Step 1: Decrypt ───────────────────────────────────────────────────
		decrypt_ok = _run(
			uv + [str(SCRIPTS_DIR / "antigravity_decrypt.py"), str(CONVERSATIONS_DIR), "--output", str(WORK_DIR), "--key", key], "DECRYPT"
		)
		if not decrypt_ok:
			logger.error("Decrypt failed. Aborting pipeline.")
			return

		# ── Step 2: Ingest ────────────────────────────────────────────────────
		ingest_ok = _run(uv + [str(SCRIPTS_DIR / "antigravity_ingest.py"), "--dir", str(WORK_DIR)], "INGEST")
		if not ingest_ok:
			logger.error("Ingest failed. Aborting pipeline.")
			return

		# ── Step 3: Distill (optional — skip if LLM not available) ───────────
		if _llm_available():
			_run(uv + [str(SCRIPTS_DIR / "chronicle_distill.py")], "DISTILL")
		else:
			logger.warning("[DISTILL] Local LLM not available. Skipping distillation — will retry on next cycle.")

		# ── Step 4: Refine ────────────────────────────────────────────────────
		_run(uv + [str(SCRIPTS_DIR / "chronicle_refine.py")], "REFINE")

		# ── Mark as processed ─────────────────────────────────────────────────
		now = datetime.now().isoformat()
		for pb in pending:
			state["processed"][pb.stem] = now
		state["last_run"] = now
		state["stats"]["total_sessions"] += len(pending)
		_save_processed(state)
		logger.info(f"Chronicle pipeline complete. {len(pending)} session(s) marked as processed.")

	finally:
		# ── Cleanup work dir ──────────────────────────────────────────────────
		if WORK_DIR.exists():
			shutil.rmtree(WORK_DIR)
			logger.info("Work dir cleaned up.")


if __name__ == "__main__":
	t0 = time.time()
	main()
	logger.info(f"Total time: {time.time() - t0:.1f}s")
