"""
Test: No Hardcoded Antigravity Paths (Agent Smith — Path Sovereignty)

Ensures all references to ~/.gemini/antigravity resolve through
core/paths.py functions, never via hardcoded strings.

Allowed files:
  - core/paths.py (canonical definitions)
  - config.py (BRAIN_PATH config field — read by paths.py)
"""

import re
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "red_pill"

# Files that are ALLOWED to contain raw .gemini/antigravity paths
ALLOWED_FILES = {
	SRC_DIR / "core" / "paths.py",
	SRC_DIR / "config.py",
}

# Patterns that indicate a hardcoded Antigravity path
HARDCODED_PATTERNS = [
	re.compile(r'["\']~?/?\.gemini/antigravity'),  # string literals
	re.compile(r'Path\.home\(\)\s*/\s*["\']\.gemini["\']'),  # Path.home() / ".gemini"
	re.compile(r'expanduser\(["\']~/\.gemini'),  # os.path.expanduser("~/.gemini")
]


def _collect_violations():
	"""Scan all .py files in src/red_pill for hardcoded Antigravity paths."""
	violations = []
	for py_file in SRC_DIR.rglob("*.py"):
		if py_file in ALLOWED_FILES:
			continue
		if "__pycache__" in str(py_file):
			continue

		try:
			content = py_file.read_text(encoding="utf-8")
		except Exception:
			continue

		for i, line in enumerate(content.splitlines(), 1):
			# Skip comments
			stripped = line.lstrip()
			if stripped.startswith("#"):
				continue

			for pattern in HARDCODED_PATTERNS:
				if pattern.search(line):
					# Allow legacy fallback lines (explicitly marked)
					if "legacy" in line.lower() or "fallback" in line.lower() or "antigravity-cli" in line:
						continue
					rel = py_file.relative_to(SRC_DIR)
					violations.append(f"{rel}:{i} - {line.strip()}")

	return violations


def test_no_hardcoded_antigravity_paths():
	"""All Antigravity IDE paths must resolve through core/paths.py — never hardcoded."""
	violations = _collect_violations()
	if violations:
		msg = "Hardcoded Antigravity paths found. Use core/paths.py functions instead:\n"
		msg += "  - get_antigravity_root()\n"
		msg += "  - get_antigravity_brain_dir()\n"
		msg += "  - get_antigravity_rules_dir()\n"
		msg += "  - get_antigravity_conversations_dir()\n\n"
		msg += "Violations:\n"
		for v in violations:
			msg += f"  {v}\n"
		pytest.fail(msg)
