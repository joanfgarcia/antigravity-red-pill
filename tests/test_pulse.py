"""
COV-001: pulse.py — Interaction Cadence Detection Tests
=========================================================
Tests for record_interaction(), _atomic_write_heartbeat(), and _human_time().

All tests use tmp_path to avoid touching the real IA_DIR heartbeat file.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import red_pill.config as cfg


@pytest.fixture(autouse=True)
def isolate_heartbeat(tmp_path):
	"""Redirect the heartbeat file to a temp directory for every test."""
	heartbeat_path = str(tmp_path / "pulse.json")
	with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
		yield heartbeat_path


class TestRecordInteraction:
	def test_first_interaction_returns_initial_status(self):
		"""First ever interaction has no previous timestamp — status is 'initial'."""
		from red_pill.utils.pulse import record_interaction

		result = record_interaction()
		assert result["status"] == "initial"
		assert result["delta_seconds"] == 0

	def test_second_interaction_calculates_delta(self, tmp_path):
		"""Second call after a gap returns a positive delta_seconds."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		with open(heartbeat_path, "w") as f:
			json.dump({"last_interaction": time.time() - 10.0}, f)
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			result = record_interaction()
			assert result["delta_seconds"] >= 9
			assert result["delta_seconds"] <= 15

	def test_burst_detection(self, tmp_path):
		"""Interactions within CADENCE_BURST_THRESHOLD are classified as 'burst'."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		with open(heartbeat_path, "w") as f:
			json.dump({"last_interaction": time.time() - 0.5}, f)
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			result = record_interaction()
			assert result["status"] == "burst"

	def test_dormant_detection(self, tmp_path):
		"""Interactions after CADENCE_ABSENCE_THRESHOLD are classified as 'dormant'."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		far_past = time.time() - (cfg.CADENCE_ABSENCE_THRESHOLD + 100)
		with open(heartbeat_path, "w") as f:
			json.dump({"last_interaction": far_past}, f)
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			result = record_interaction()
			assert result["status"] == "dormant"

	def test_normal_cadence(self, tmp_path):
		"""Interaction after a moderate gap returns 'normal' status."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		mid_gap = time.time() - (cfg.CADENCE_BURST_THRESHOLD + cfg.CADENCE_ABSENCE_THRESHOLD) / 2
		with open(heartbeat_path, "w") as f:
			json.dump({"last_interaction": mid_gap}, f)
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			result = record_interaction()
			assert result["status"] == "normal"

	def test_heartbeat_file_written_after_interaction(self, tmp_path):
		"""record_interaction() must persist a heartbeat file after each call."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			record_interaction()
			assert Path(heartbeat_path).exists()
			with open(heartbeat_path) as f:
				data = json.load(f)
			assert "last_interaction" in data
			assert data["last_interaction"] > 0

	def test_corrupted_heartbeat_file_handled_gracefully(self, tmp_path):
		"""Corrupted heartbeat JSON is silently ignored — treated as first interaction."""
		from red_pill.utils.pulse import record_interaction

		heartbeat_path = str(tmp_path / "pulse.json")
		with open(heartbeat_path, "w") as f:
			f.write("{not valid json")
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			result = record_interaction()
			assert result["status"] == "initial"


class TestAtomicWrite:
	def test_atomic_write_creates_file(self, tmp_path):
		"""_atomic_write_heartbeat creates the target file atomically."""
		from red_pill.utils.pulse import _atomic_write_heartbeat

		heartbeat_path = str(tmp_path / "pulse.json")
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			_atomic_write_heartbeat({"last_interaction": 12345.0, "prev_interaction": 0.0})
			assert Path(heartbeat_path).exists()

	def test_atomic_write_no_temp_file_left_behind(self, tmp_path):
		"""No .tmp file should remain after a successful write."""
		from red_pill.utils.pulse import _atomic_write_heartbeat

		heartbeat_path = str(tmp_path / "pulse.json")
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			_atomic_write_heartbeat({"last_interaction": 12345.0, "prev_interaction": 0.0})
			assert not Path(heartbeat_path + ".tmp").exists()

	def test_atomic_write_content_is_valid_json(self, tmp_path):
		"""Written file must be valid JSON with the expected keys."""
		from red_pill.utils.pulse import _atomic_write_heartbeat

		heartbeat_path = str(tmp_path / "pulse.json")
		with patch("red_pill.utils.pulse.HEARTBEAT_FILE", heartbeat_path):
			_atomic_write_heartbeat({"last_interaction": 9999.5, "prev_interaction": 1234.0})
			with open(heartbeat_path) as f:
				data = json.load(f)
			assert data["last_interaction"] == pytest.approx(9999.5)
			assert data["prev_interaction"] == pytest.approx(1234.0)


class TestHumanTime:
	def test_seconds(self):
		from red_pill.utils.pulse import _human_time

		assert _human_time(45) == "45s"

	def test_minutes(self):
		from red_pill.utils.pulse import _human_time

		assert _human_time(90) == "1m"

	def test_hours(self):
		from red_pill.utils.pulse import _human_time

		assert _human_time(3700) == "1h"

	def test_days(self):
		from red_pill.utils.pulse import _human_time

		assert _human_time(86401) == "1d"

	def test_zero(self):
		from red_pill.utils.pulse import _human_time

		assert _human_time(0) == "0s"
