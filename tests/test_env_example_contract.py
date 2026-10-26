"""Contract for the shipped .env template (installer seed)."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_parses_and_has_no_conflict_markers():
	path = ROOT / ".env.example"
	text = path.read_text(encoding="utf-8")
	lines = {line.strip() for line in text.splitlines()}
	for marker in ("<<<<<<<", "=======", ">>>>>>>"):
		assert marker not in lines
	assert text.endswith("\n")
	values = dotenv_values(path)
	assert values
	assert "SESSION_COMPACTOR_ENABLED" in values
	assert "AUTO_HEAL_ENABLED" in values
