"""Path Sovereignty — no hardcoded home/XDG/absolute-user paths in src/red_pill.

Every filesystem path must resolve through `core/paths.py` (the sole owner of the
XDG/config/data/state/tmp/forge roots). Modules must not hardcode `Path.home()`,
`~/…`, `/home/<user>/…` literals, or read `XDG_*_HOME` themselves.

Allowed:
  - `core/paths.py` (canonical definitions)
  - `config.py` (config/env layer that paths.py reads)

Documented exception (third-party harness dirs discovered by convention — not
red-pill's own XDG namespace): `.gemini`, `.claude`, `.pi`, `.opencode`.

Scope: `src/red_pill/**`. `scripts/**` is NOT gated yet — but excluding ALL of it
is only legitimate for the **pre-seed** scripts (those that run before the first
seeding instantiates `.env` and before `red_pill` is importable): `install_neo.sh`,
`upgrade.sh`, `scripts/inject*`, `scripts/_config_common.py`, `scripts/*/bootstrap.sh`.
The remaining `scripts/**` utilities are **debt** to migrate to `core/paths.py`
(tracked separately — do not add new hardcoded paths there).
"""

import re
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "red_pill"

# Files allowed to hold path resolution logic.
ALLOWED_FILES = {
	SRC_DIR / "core" / "paths.py",
	SRC_DIR / "config.py",
}

# Files that legitimately reference THIRD-PARTY harness dirs (.gemini/.claude/.pi/
# .opencode), discovered by convention — outside red-pill's XDG ownership.
EXTERNAL_TOOL_FILES = {
	SRC_DIR / "plugins" / "antigravity_ide" / "agy_bridge.py",
	SRC_DIR / "plugins" / "antigravity_ide" / "telegram_extractor.py",
	SRC_DIR / "chronicle_sources" / "pi.py",
	SRC_DIR / "chronicle_sources" / "claude_code.py",
	SRC_DIR / "chronicle_sources" / "opencode.py",
	SRC_DIR / "swarm" / "bridges" / "pi.py",
	SRC_DIR / "swarm" / "bridges" / "opencode.py",
	SRC_DIR / "swarm" / "autonomous_cron.py",
}

# Hardcoded path patterns (literals only — NOT `expanduser(variable)`, which merely
# resolves a user/config-provided path).
HARDCODED_PATTERNS = [
	re.compile(r'["\']~/[^"\']'),  # "~/…" or '~/…' (a path, not a bare "~/" token)
	re.compile(r'["\']/(?:home|Users|root)/'),  # "/home/<user>/…"
	re.compile(r"Path\.home\(\)\s*/"),  # Path.home() / "…"
	re.compile(r'expanduser\(\s*["\']~'),  # os.path.expanduser("~/…")
	re.compile(r'["\']XDG_(?:DATA|CONFIG|STATE|CACHE|RUNTIME)_HOME["\']'),  # raw XDG read
]


def _collect_violations():
	violations = []
	for py_file in SRC_DIR.rglob("*.py"):
		if py_file in ALLOWED_FILES or py_file in EXTERNAL_TOOL_FILES:
			continue
		if "__pycache__" in str(py_file):
			continue
		try:
			content = py_file.read_text(encoding="utf-8")
		except Exception:
			continue
		for i, line in enumerate(content.splitlines(), 1):
			if line.lstrip().startswith("#"):
				continue
			for pattern in HARDCODED_PATTERNS:
				if pattern.search(line):
					if "legacy" in line.lower() or "fallback" in line.lower():
						continue
					rel = py_file.relative_to(SRC_DIR)
					violations.append(f"{rel}:{i} - {line.strip()}")
	return violations


def test_no_hardcoded_paths():
	"""No hardcoded home/XDG/absolute-user paths outside core/paths.py (+config.py)."""
	violations = _collect_violations()
	if violations:
		msg = "Hardcoded paths found. Resolve them through core/paths.py:\n"
		msg += "  (see CONVENTIONS.md §7 — path resolution)\n\nViolations:\n"
		msg += "\n".join(f"  {v}" for v in violations)
		pytest.fail(msg)
