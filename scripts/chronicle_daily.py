#!/usr/bin/env python3
"""
chronicle_daily.py — Autonomous Chronicle Ingestion Pipeline (Phase 2)

Automates the ingestion of extracted JSON conversations into the Qdrant Bünker.
Reads from `~/.local/share/red-pill/unencrypted_conversations` and relies on a registry
to track `step_count` for each conversation, preventing duplicate or redundant ingests.

Usage:
	uv run python scripts/chronicle_daily.py              # default: process updates
	uv run python scripts/chronicle_daily.py --all       # force check all
	uv run python scripts/chronicle_daily.py --dry-run   # show what would be processed
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("chronicle_daily")

# ── Paths ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from red_pill.core.paths import get_data_dir

PROCESSED_LOG = get_data_dir() / "chronicle_daily_registry.json"
WORK_DIR = Path("/tmp/chronicle_today")
SCRIPTS_DIR = Path(__file__).parent


def _load_processed() -> dict:
	"""Load the registry of processed session IDs and their step counts."""
	if PROCESSED_LOG.exists():
		try:
			return json.loads(PROCESSED_LOG.read_text())
		except Exception:
			pass

	# Auto-seed registry with existing files to prevent massive ingestion timeouts on new installations
	state = {"processed": {}, "registry": {}, "last_run": None, "stats": {"total_ingested": 0, "total_sessions": 0}}
	try:
		from red_pill.core.paths import get_unencrypted_conversations_dir
		unencrypted_dir = get_unencrypted_conversations_dir()
		if unencrypted_dir.exists():
			now = datetime.now().isoformat()
			for json_file in unencrypted_dir.glob("*.json"):
				cid = json_file.stem
				try:
					data = json.loads(json_file.read_text(encoding="utf-8"))
					step_count = data.get("step_count", 0)
					state["registry"][cid] = step_count
					state["processed"][cid] = now
				except Exception:
					continue
			state["last_run"] = now
			state["stats"]["total_sessions"] = len(state["registry"])
			PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
			PROCESSED_LOG.write_text(json.dumps(state, indent=2))
			logger.info(f"Auto-seeded chronicle registry with {len(state['registry'])} existing sessions.")
	except Exception as e:
		logger.warning(f"Failed to auto-seed chronicle registry: {e}")

	return state


def _save_processed(state: dict) -> None:
	PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
	PROCESSED_LOG.write_text(json.dumps(state, indent=2))


def _find_pending(state: dict, force_all: bool = False) -> list[tuple[Path, int]]:
	"""Return a list of (Path, step_count) for JSONs that need to be ingested."""
	from red_pill.core.paths import get_unencrypted_conversations_dir

	unencrypted_dir = get_unencrypted_conversations_dir()
	if not unencrypted_dir.exists():
		logger.error(f"Unencrypted conversations dir not found: {unencrypted_dir}")
		return []

	pending = []
	registry = state.setdefault("registry", {})

	for json_file in sorted(unencrypted_dir.glob("*.json")):
		cid = json_file.stem
		try:
			data = json.loads(json_file.read_text(encoding="utf-8"))
			step_count = data.get("step_count", 0)
		except Exception as e:
			logger.warning(f"Could not read {json_file.name}: {e}")
			continue

		last_step_count = registry.get(cid, -1)

		# Only ingest if the JSON has more steps than what we last recorded
		if force_all or step_count > last_step_count:
			pending.append((json_file, step_count))

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
	base = url.rsplit("/", 2)[0]
	try:
		urllib.request.urlopen(base, timeout=3)
		return True
	except Exception:
		return False


def main() -> None:
	parser = argparse.ArgumentParser(description="Autonomous Chronicle Ingestion Pipeline")
	parser.add_argument("--all", action="store_true", help="Process all unprocessed conversations")
	parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without doing anything")
	args = parser.parse_args()

	# ── Load state ────────────────────────────────────────────────────────────
	state = _load_processed()
	pending_tuples = _find_pending(state, force_all=args.all)

	if not pending_tuples:
		logger.info("No pending conversations to process. Registry is up to date.")
		state["last_run"] = datetime.now().isoformat()
		_save_processed(state)
		return

	logger.info(f"Found {len(pending_tuples)} pending conversation(s) requiring ingestion.")
	for p, count in pending_tuples:
		logger.info(f"  → {p.name} (Steps: {count})")

	if args.dry_run:
		logger.info("[DRY RUN] No changes made.")
		return

	# ── Prepare work dir ──────────────────────────────────────────────────────
	if WORK_DIR.exists():
		shutil.rmtree(WORK_DIR)
	WORK_DIR.mkdir(parents=True)

	try:
		uv = ["uv", "run", "python"]

		# ── Copy pending JSONs to isolated WORK_DIR ───────────────────────────
		for json_file, _ in pending_tuples:
			shutil.copy2(json_file, WORK_DIR)

		# ── Step 1: Ingest ────────────────────────────────────────────────────
		ingest_ok = _run(uv + [str(SCRIPTS_DIR / "antigravity_ingest.py"), "--dir", str(WORK_DIR)], "INGEST")
		if not ingest_ok:
			logger.error("Ingest failed. Aborting pipeline.")
			return

		# ── Step 2: Distill (Samantha) ───────────────────────────────────────
		if _llm_available():
			_run(uv + [str(SCRIPTS_DIR / "chronicle_distill.py")], "DISTILL")
		else:
			logger.warning("[DISTILL] Local LLM not available. Skipping Samantha distillation — will retry on next cycle.")

		# ── Step 3: Refine ────────────────────────────────────────────────────
		_run(uv + [str(SCRIPTS_DIR / "chronicle_refine.py")], "REFINE")

		# ── Mark as processed in Registry ─────────────────────────────────────
		now = datetime.now().isoformat()
		for json_file, step_count in pending_tuples:
			cid = json_file.stem
			state["registry"][cid] = step_count
			state["processed"][cid] = now

		state["last_run"] = now
		state["stats"]["total_sessions"] += len(pending_tuples)
		_save_processed(state)
		logger.info(f"Chronicle pipeline complete. {len(pending_tuples)} session(s) updated in the registry.")

	finally:
		if WORK_DIR.exists():
			shutil.rmtree(WORK_DIR)


if __name__ == "__main__":
	main()
