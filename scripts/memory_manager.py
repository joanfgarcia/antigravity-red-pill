#!/usr/bin/env python3
import sys
from red_pill.cli import main

if __name__ == "__main__":
	# Simple compatibility wrapper for the Red Pill CLI
	# Forwards all arguments to the main CLI entry point.
	sys.exit(main())
