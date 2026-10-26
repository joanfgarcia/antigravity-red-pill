"""Contract for the shipped .env template (installer seed)."""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class _Capture(logging.Handler):
	def __init__(self):
		super().__init__()
		self.records = []

	def emit(self, record):
		self.records.append(record.getMessage())


def _parse(path: Path) -> tuple[dict, list[str]]:
	logger = logging.getLogger("dotenv.main")
	capture = _Capture()
	logger.addHandler(capture)
	try:
		values = dotenv_values(path)
	finally:
		logger.removeHandler(capture)
	warnings = [message for message in capture.records if "could not parse" in message]
	return dict(values), warnings


def _conflict_markers(text: str) -> list[str]:
	return [
		line
		for line in text.splitlines()
		if line.strip().startswith(("<<<<<<<", ">>>>>>>", "======="))
	]


def test_env_example_parses_and_has_no_conflict_markers():
	path = ROOT / ".env.example"
	text = path.read_text(encoding="utf-8")
	assert _conflict_markers(text) == []
	assert text.endswith("\n")
	values, warnings = _parse(path)
	assert warnings == []
	assert values
	assert "SESSION_COMPACTOR_ENABLED" in values
	assert "AUTO_HEAL_ENABLED" in values


def test_env_example_guard_detects_conflict_and_parse_failure(tmp_path):
	bad = tmp_path / "bad.env"
	bad.write_text("<<<<<<< HEAD\nA=1\n=======\nBROKEN='unterminated\n>>>>>>> main\n", encoding="utf-8")
	text = bad.read_text(encoding="utf-8")
	assert _conflict_markers(text)
	_, warnings = _parse(bad)
	assert warnings
