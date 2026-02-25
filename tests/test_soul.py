from unittest.mock import MagicMock, patch

import pytest

from red_pill.soul import SoulManager


@pytest.fixture
def mock_requests():
	with patch("red_pill.soul.requests") as mock:
		yield mock


@pytest.fixture
def soul_manager(mock_requests):
	# Mocking all filesystem interactions globally for the fixture
	with (
		patch("red_pill.soul.os.makedirs"),
		patch("red_pill.soul.os.path.exists", return_value=True),
		patch("red_pill.soul.os.path.expanduser", side_effect=lambda x: x.replace("~", "/fake/home")),
	):
		manager = SoulManager()
		manager.ia_dir = "/fake/ia_dir"
		manager.backup_root = "/fake/ia_dir/backups"
		yield manager


def test_get_collections(soul_manager, mock_requests):
	mock_requests.get.return_value.json.return_value = {"result": {"collections": [{"name": "col1"}, {"name": "col2"}]}}
	collections = soul_manager._get_collections()
	assert collections == ["col1", "col2"]


@patch("red_pill.soul.open", create=True)
@patch("red_pill.soul.shutil.copyfileobj")
def test_backup_qdrant(mock_copy, mock_open, soul_manager, mock_requests):
	soul_manager._get_collections = MagicMock(return_value=["col1"])
	mock_requests.post.return_value.json.return_value = {"result": {"name": "snap1"}}
	# Mock the stream response
	mock_requests.get.return_value.__enter__.return_value.raw = MagicMock()

	saved = soul_manager.backup_qdrant("ts")
	assert len(saved) == 1
	assert "col1_ts.snapshot" in saved[0]


@patch("red_pill.soul.shutil.copy2")
@patch("red_pill.soul.shutil.copytree")
@patch("red_pill.soul.shutil.rmtree")
def test_backup_files(mock_rmtree, mock_copytree, mock_copy2, soul_manager):
	# We are already patched by the fixture for os.makedirs and path.exists
	soul_manager.backup_files("ts")
	# Check if any copy operation was attempted (should be, since exists=True)
	assert mock_copy2.called or mock_copytree.called


@patch("red_pill.soul.tarfile.open")
def test_export_soul(mock_tar, soul_manager):
	soul_manager.full_backup = MagicMock()
	soul_manager.export_soul("fake_path.tar.gz")
	assert soul_manager.full_backup.called
	assert mock_tar.called


@patch("red_pill.soul.os.walk")
@patch("red_pill.soul.shutil.copy2")
def test_restore_soul_dry_run(mock_copy2, mock_walk, soul_manager):
	mock_walk.return_value = [("/fake/home", [], ["fake.md"])]
	soul_manager.restore_soul("/fake/backup", commit=False)
	assert not mock_copy2.called


@patch("red_pill.soul.os.walk")
@patch("red_pill.soul.shutil.copy2")
@patch("red_pill.soul.os.listdir")
def test_restore_soul_commit(mock_listdir, mock_copy2, mock_walk, soul_manager, mock_requests):
	mock_walk.return_value = [("/fake/home/rel", [], ["fake.md"])]
	mock_listdir.return_value = ["col1_ts.snapshot"]

	with patch("red_pill.soul.open", create=True):
		soul_manager.restore_soul("/fake/backup", commit=True)

	assert mock_copy2.called
	assert mock_requests.post.called  # Snapshot upload upload
