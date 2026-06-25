#!/usr/bin/env python3
"""Thin runnable wrapper for `red-pill doctor`. Logic lives in red_pill.metabolism.doctor.

Run after an install/update (or by hand) for an immediate config↔runtime verdict:
	uv run python scripts/doctor.py [--quiet]
Exit code: 0 = ok (green/yellow), 1 = red (something broken) — usable as a gate.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from red_pill.metabolism.doctor import run_doctor

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="On-demand config<->runtime health verification.")
	parser.add_argument("--quiet", action="store_true", help="Solo el veredicto (oculta info no-bloqueante).")
	args = parser.parse_args()
	sys.exit(run_doctor(quiet=args.quiet))
