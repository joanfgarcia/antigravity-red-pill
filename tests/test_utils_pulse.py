"""Tests for utils/pulse.py — targeting uncovered lines 59-65 (_atomic_write_heartbeat error paths)."""

import json
import os
from unittest.mock import patch

import pytest

from red_pill.utils.pulse import _atomic_write_heartbeat, _human_time, record_interaction


class TestAtomicWriteHeartbeat:
	def test_write_failure_cleans_up_tmp(self, tmp_path):
		"""Lines 59-65: write fails → tmp file unlinked, exception re-raised."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		with patch("os.fsync", side_effect=OSError("disk full")):
			with pytest.raises(OSError):
				_atomic_write_heartbeat({"last_interaction": 1.0, "prev_interaction": 0.0})
		tmp_file = pulse_mod.HEARTBEAT_FILE + ".tmp"
		assert not os.path.exists(tmp_file)
		pulse_mod.HEARTBEAT_FILE = original

	def test_write_failure_unlink_oserror_suppressed(self, tmp_path):
		"""Lines 61-64: unlink also fails → OSError suppressed, original re-raised."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		with patch("os.fsync", side_effect=OSError("disk full")):
			with patch("os.unlink", side_effect=OSError("already gone")):
				with pytest.raises(OSError, match="disk full"):
					_atomic_write_heartbeat({"last_interaction": 1.0, "prev_interaction": 0.0})
		pulse_mod.HEARTBEAT_FILE = original

	def test_successful_write(self, tmp_path):
		"""Normal path: data written, replace called, tmp gone."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "storage" / "pulse.json")
		data = {"last_interaction": 123.0, "prev_interaction": 0.0}
		_atomic_write_heartbeat(data)
		result_path = pulse_mod.HEARTBEAT_FILE
		with open(result_path) as f:
			saved = json.load(f)
		assert saved["last_interaction"] == 123.0
		pulse_mod.HEARTBEAT_FILE = original


class TestRecordInteraction:
	def test_initial_status_no_file(self, tmp_path):
		"""Lines 32-33: no previous file → status='initial'."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		result = record_interaction()
		assert result["status"] == "initial"
		pulse_mod.HEARTBEAT_FILE = original

	def test_burst_status(self, tmp_path):
		"""Lines 34-35: delta < CADENCE_BURST_THRESHOLD → status='burst'."""
		import time

		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		data = {"last_interaction": time.time() - 1}
		with open(str(tmp_path / "pulse.json"), "w") as f:
			json.dump(data, f)
		result = record_interaction()
		assert result["status"] == "burst"
		pulse_mod.HEARTBEAT_FILE = original

	def test_dormant_status(self, tmp_path):
		"""Lines 36-37: delta > CADENCE_ABSENCE_THRESHOLD → status='dormant'."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		import time

		data = {"last_interaction": time.time() - 86400 * 30}
		with open(str(tmp_path / "pulse.json"), "w") as f:
			json.dump(data, f)
		result = record_interaction()
		assert result["status"] == "dormant"
		pulse_mod.HEARTBEAT_FILE = original

	def test_corrupt_heartbeat_file_ignored(self, tmp_path):
		"""Lines 21-22: corrupt JSON → silently ignored, proceeds normally."""
		import red_pill.utils.pulse as pulse_mod

		original = pulse_mod.HEARTBEAT_FILE
		pulse_mod.HEARTBEAT_FILE = str(tmp_path / "pulse.json")
		with open(str(tmp_path / "pulse.json"), "w") as f:
			f.write("NOT JSON AT ALL }{")
		result = record_interaction()
		assert result["status"] == "initial"
		pulse_mod.HEARTBEAT_FILE = original


class TestHumanTime:
	def test_seconds(self):
		assert _human_time(45) == "45s"

	def test_minutes(self):
		assert _human_time(90) == "1m"

	def test_hours(self):
		assert _human_time(7200) == "2h"

	def test_days(self):
		assert _human_time(172800) == "2d"
