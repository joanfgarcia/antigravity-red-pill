import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch, MagicMock

from red_pill.swarm.agents.janitor import JanitorMinion


@pytest.fixture
def temp_dir():
	with tempfile.TemporaryDirectory() as tmpdir:
		yield Path(tmpdir)


def test_janitor_log_rotation_and_cleanup(temp_dir):
	# Create a mock active log file with content
	log_file = temp_dir / "error.log"
	log_file.write_text("some error log content here")
	assert log_file.exists()

	# Create some existing backups
	backup1 = temp_dir / "error.log.1"
	backup1.write_text("old content 1")
	backup2 = temp_dir / "error.log.2"
	backup2.write_text("old content 2")

	# Make backup2 old (e.g. 40 days old) to test cleanup
	old_time = (datetime.now() - timedelta(days=40)).timestamp()
	os.utime(backup2, (old_time, old_time))

	# Initialize janitor
	janitor = JanitorMinion()
	object.__setattr__(janitor, 'log', MagicMock())

	# Test copytruncate rotation
	assert log_file.stat().st_size > 0
	janitor._rotate_file_copytruncate(log_file)

	# Verify active log is truncated to size 0
	assert log_file.exists()
	assert log_file.stat().st_size == 0

	# Verify backup 1 now has the active content
	rotated_1 = temp_dir / "error.log.1"
	assert rotated_1.exists()
	assert rotated_1.read_text() == "some error log content here"

	# Verify backup 2 now has the shifted content from old backup 1
	rotated_2 = temp_dir / "error.log.2"
	assert rotated_2.exists()
	assert rotated_2.read_text() == "old content 1"

	# Test cleanup of old logs
	# Set mtime of rotated_2 to 40 days ago to trigger expiration
	os.utime(rotated_2, (old_time, old_time))

	purged = janitor._cleanup_old_rotated_logs(temp_dir, "error.log", days=30)
	assert purged == 2
	assert not rotated_2.exists()
	assert rotated_1.exists()
