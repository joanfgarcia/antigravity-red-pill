"""Path Sovereignty — no hardcoded home/XDG/absolute-user paths in src/red_pill + scripts.

Every filesystem path must resolve through `core/paths.py` (the sole owner of the
XDG/config/data/state/tmp/forge roots). Modules/scripts must not hardcode
`Path.home()`, `~/…`, `/home/<user>/…` literals, or read `XDG_*_HOME` themselves.

Allowed:
  - `core/paths.py` (canonical definitions)
  - `config.py` (config/env layer that paths.py reads)
  - third-party harness dirs discovered by convention (`.gemini`/`.claude`/`.pi`/`.opencode`)
  - a BOUNDED list of **pre-seed** scripts (run before the first seeding instantiates
    `.env` and before `red_pill` is importable). A NEW pre-seed script MUST be added
    to `SCRIPTS_PRE_SEED` (or the `scripts/inject/` package) so the test skips it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src" / "red_pill"
SCRIPTS_DIR = ROOT / "scripts"

ALLOWED_FILES = {
	SRC_DIR / "core" / "paths.py",
	SRC_DIR / "config.py",
}

# Third-party harness dirs (.gemini/.claude/.pi/.opencode), discovered by convention.
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

# BOUNDED list of pre-seed scripts (install/inject run before `.env`/red_pill exist).
SCRIPTS_PRE_SEED = {
	SCRIPTS_DIR / "_config_common.py",
	SCRIPTS_DIR / "inject_cli.py",
	SCRIPTS_DIR / "inject_anchor.py",
	SCRIPTS_DIR / "inject_mcp.py",
	SCRIPTS_DIR / "inject_settings.py",
	SCRIPTS_DIR / "inject_opencode.py",
	SCRIPTS_DIR / "migrate_prompt_language.py",
}
INJECT_PKG = SCRIPTS_DIR / "inject"

HARDCODED_PATTERNS = [
	re.compile(r'["\']~/[^"\']'),  # "~/…" (a path, not a bare "~/" token)
	re.compile(r'["\']/(?:home|Users|root)/'),  # "/home/<user>/…"
	re.compile(r"Path\.home\(\)\s*/"),  # Path.home() / "…"
	re.compile(r'expanduser\(\s*["\']~'),  # os.path.expanduser("~/…")
	re.compile(r'(?:os\.environ\.get|os\.getenv)\(\s*["\']XDG_(?:DATA|CONFIG|STATE|CACHE|RUNTIME)_HOME'),  # raw XDG read
]


def _is_allowed(py: Path) -> bool:
	if py in ALLOWED_FILES or py in EXTERNAL_TOOL_FILES or py in SCRIPTS_PRE_SEED:
		return True
	return INJECT_PKG in py.parents  # the whole scripts/inject/** package (IDE injectors)


def _collect_violations():
	violations = []
	for base in (SRC_DIR, SCRIPTS_DIR):
		for py_file in base.rglob("*.py"):
			if _is_allowed(py_file) or "__pycache__" in str(py_file):
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
						rel = py_file.relative_to(ROOT)
						violations.append(f"{rel}:{i} - {line.strip()}")
	return violations


def test_no_hardcoded_paths():
	"""No hardcoded home/XDG/absolute-user paths outside core/paths.py (+ allowlists)."""
	violations = _collect_violations()
	if violations:
		msg = "Hardcoded paths found. Resolve them through core/paths.py:\n"
		msg += "  (see CONVENTIONS.md §7 — path resolution)\n\nViolations:\n"
		msg += "\n".join(f"  {v}" for v in violations)
		pytest.fail(msg)
