#!/usr/bin/env python3
"""
Prototype: The Red Button (Scorched Earth Protocol)
ROADMAP Ticket: Encrypted one-click "Scorched Earth" protocol for instant bunker purge.

Description:
This script securely wipes the Qdrant cortex and the SQLite SQLite Minion inbox
to prevent data recovery. It acts as an emergency reset.
"""
import logging
import os
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RedButton")

QDRANT_DATA_DIR = Path("~/.local/share/qdrant").expanduser()
MINION_DB = Path("~/.config/neon-link/minion_inbox.db").expanduser()
BUNKER_SECRETS = Path("~/.config/red-pill/.env").expanduser()

def shred_file(path: Path, passes: int = 3):
    if not path.exists():
        return
    logger.info(f"Shredding {path} ({passes} passes)...")
    length = path.stat().st_size
    with open(path, "br+") as f:
        for _ in range(passes):
            f.seek(0)
            f.write(os.urandom(length))
    path.unlink()
    logger.info(f"File {path} destroyed.")

def execute_scorched_earth():
    logger.warning("INITIATING SCORCHED EARTH PROTOCOL")

    # 1. Destroy SQLite DB
    shred_file(MINION_DB)

    # 2. Destroy Secrets
    shred_file(BUNKER_SECRETS)

    # 3. Wipe Qdrant Data
    if QDRANT_DATA_DIR.exists():
        logger.info(f"Wiping Qdrant vectors at {QDRANT_DATA_DIR}")
        shutil.rmtree(QDRANT_DATA_DIR)

    logger.warning("BÜNKER PURGED SUCCESSFULLY. SYSTEM INERT.")

if __name__ == "__main__":
    execute_scorched_earth()
