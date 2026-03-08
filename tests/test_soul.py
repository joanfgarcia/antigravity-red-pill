"""Tests for soul.py — targeting lines 37-39, 67-68, 82-98, 102-105, 125, 139-141, 149, 198-199."""

import json
import os
import tarfile
import time
from unittest.mock import MagicMock, patch

import pytest

from red_pill.soul import SoulManager


@pytest.fixture
def soul(tmp_path):
	with patch("red_pill.soul.CloudVault") as MockVault:
		MockVault.return_value.enabled = False
		sm = SoulManager()
		sm.ia_dir = str(tmp_path)
		sm.backup_root = str(tmp_path / "backups")
		yield sm


# ---------------------------------------------------------------------------
# Lines 37-39: _get_collections exception
# ---------------------------------------------------------------------------


class TestGetCollections:
	def test_request_exception_returns_empty(self, soul):
		"""Lines 37-39: requests.get fails → returns []."""
		with patch("requests.get", side_effect=Exception("timeout")):
			result = soul._get_collections()
		assert result == []

	def test_successful_fetch(self, soul):
		"""Lines 33-36: successful GET → list of collection names."""
		mock_resp = MagicMock()
		mock_resp.json.return_value = {"result": {"collections": [{"name": "work"}, {"name": "social"}]}}
		with patch("requests.get", return_value=mock_resp):
			result = soul._get_collections()
		assert result == ["work", "social"]


# ---------------------------------------------------------------------------
# Lines 67-68: backup_qdrant per-collection exception
# ---------------------------------------------------------------------------


class TestBackupQdrant:
	def test_collection_backup_exception_logged(self, soul, tmp_path):
		"""Lines 67-68: POST for snapshot fails → exception caught per-collection."""
		with patch.object(soul, "_get_collections", return_value=["work"]):
			with patch("requests.post", side_effect=Exception("Qdrant down")):
				result = soul.backup_qdrant("20260101_120000")
		# Should return empty (no successful saves)
		assert result == []

	def test_successful_snapshot_saved(self, soul, tmp_path):
		"""Lines 50-66: snapshot created and downloaded successfully."""
		mock_post = MagicMock()
		mock_post.json.return_value = {"result": {"name": "snap1.snapshot"}}

		mock_get_resp = MagicMock()
		mock_get_resp.__enter__ = lambda s: s
		mock_get_resp.__exit__ = MagicMock(return_value=False)
		mock_get_resp.raw = MagicMock()

		with patch.object(soul, "_get_collections", return_value=["work"]):
			with patch("requests.post", return_value=mock_post):
				with patch("requests.get", return_value=mock_get_resp):
					with patch("shutil.copyfileobj"):
						result = soul.backup_qdrant("20260101_120000")
		assert len(result) == 1
		assert "work_20260101_120000.snapshot" in result[0]


# ---------------------------------------------------------------------------
# Lines 82-98: create_manifest writes JSON file
# ---------------------------------------------------------------------------


class TestCreateManifest:
	def test_manifest_written_to_disk(self, soul, tmp_path):
		"""Lines 82-98: manifest JSON created with correct keys."""
		result = soul.create_manifest("20260101_120000")
		assert os.path.exists(result)
		with open(result) as f:
			data = json.load(f)
		assert "protocol_version" in data
		assert "schema_version" in data
		assert data["timestamp"] == "20260101_120000"


# ---------------------------------------------------------------------------
# Lines 102-105: full_backup calls backup_qdrant and create_manifest
# ---------------------------------------------------------------------------


class TestFullBackup:
	def test_full_backup_calls_both(self, soul, capsys):
		"""Lines 102-105: full_backup runs qdrant + manifest."""
		with patch.object(soul, "backup_qdrant") as mock_bq:
			with patch.object(soul, "create_manifest") as mock_cm:
				soul.full_backup()
				assert mock_bq.called
				assert mock_cm.called
		captured = capsys.readouterr()
		assert "Lean Soul Backup completed" in captured.out


# ---------------------------------------------------------------------------
# Line 125: export_soul auto-generates output_path when None
# ---------------------------------------------------------------------------


class TestExportSoul:
	def test_auto_output_path_generated(self, soul, tmp_path, capsys):
		"""Line 124-125: no output_path → auto-generated from timestamp."""
		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				with patch("os.listdir", return_value=[]):
					soul.export_soul(output_path=None)
		captured = capsys.readouterr()
		assert "LEAN_SOUL_KIT" in captured.out

	def test_snapshot_added_to_tar(self, soul, tmp_path, capsys):
		"""Lines 138-141: snapshot files matching timestamp are added to tar."""
		ts = time.strftime("%Y%m%d_%H%M%S")
		snap_dir = tmp_path / "backups" / "qdrant"
		snap_dir.mkdir(parents=True)
		snap_file = snap_dir / f"work_{ts}.snapshot"
		snap_file.write_bytes(b"snapshot_data")

		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				output = str(tmp_path / "export.tar.gz")
				soul.export_soul(output_path=output)

		assert os.path.exists(output)
		with tarfile.open(output, "r:gz") as tar:
			names = tar.getnames()
		assert any("work_" in n for n in names)

	def test_cloud_upload_success_printed(self, soul, tmp_path, capsys):
		"""Line 148-149: vault upload succeeds → prints file_id."""
		soul.vault.enabled = True
		soul.vault.upload_kit.return_value = "gdrive_file_123"

		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				with patch("os.listdir", return_value=[]):
					output = str(tmp_path / "export.tar.gz")
					soul.export_soul(output_path=output)

		captured = capsys.readouterr()
		assert "gdrive_file_123" in captured.out

	def test_cloud_upload_failure_printed(self, soul, tmp_path, capsys):
		"""Line 151: vault upload returns falsy → prints failure message."""
		soul.vault.enabled = True
		soul.vault.upload_kit.return_value = None  # falsy

		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				with patch("os.listdir", return_value=[]):
					output = str(tmp_path / "export.tar.gz")
					soul.export_soul(output_path=output)

		captured = capsys.readouterr()
		assert "Cloud Transmission Failed" in captured.out

	def test_manifest_not_added_when_missing(self, soul, tmp_path, capsys):
		"""tar created but manifest absent → archive still created."""
		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				with patch("os.listdir", return_value=[]):
					output = str(tmp_path / "export.tar.gz")
					soul.export_soul(output_path=output)
		assert os.path.exists(output)

	def test_manifest_added_to_tar_when_exists(self, soul, tmp_path, capsys):
		"""Line 136: manifest file exists → added to tar as 'manifest.json'."""
		ts = time.strftime("%Y%m%d_%H%M%S")
		snap_dir = tmp_path / "backups" / "qdrant"
		snap_dir.mkdir(parents=True)
		manifest_file = snap_dir / f"manifest_{ts}.json"
		manifest_file.write_text('{"test": true}')

		with patch.object(soul, "backup_qdrant"):
			with patch.object(soul, "create_manifest"):
				with patch("time.strftime", return_value=ts):
					output = str(tmp_path / "export.tar.gz")
					soul.export_soul(output_path=output)

		with tarfile.open(output, "r:gz") as tar:
			assert "manifest.json" in tar.getnames()


# ---------------------------------------------------------------------------
# Lines 77-78: backup_files deprecated
# ---------------------------------------------------------------------------


class TestBackupFilesDeprecated:
	def test_returns_empty_string(self, soul):
		"""Lines 77-78: deprecated method → logs warning, returns ''."""
		result = soul.backup_files("20260101")
		assert result == ""


# ---------------------------------------------------------------------------
# Lines 170-172: restore_soul commit actually copies files
# ---------------------------------------------------------------------------


class TestRestoreSoulCommit:
	def test_commit_true_restores_snapshots(self, soul, tmp_path):
		"""Lines 184-212: commit=True → snapshot restore called."""
		# Create a dummy snapshot file
		snap_dir = tmp_path / "snapshots"
		snap_dir.mkdir()
		snap_file = snap_dir / "work_20260101.snapshot"
		snap_file.write_bytes(b"data")

		mock_resp = MagicMock()
		mock_resp.raise_for_status.return_value = None
		with patch("requests.post", return_value=mock_resp):
			soul.restore_soul(str(tmp_path), commit=True)
			# Requests should be called (one check, one restore)
			assert mock_resp.raise_for_status.called

	def test_commit_no_snapshots_skips_gracefully(self, soul, tmp_path):
		"""Line 179: commit=True but no snapshots found → error logged."""
		soul.restore_soul(str(tmp_path), commit=True)  # Must not raise


class TestRestoreSoul:
	def test_snapshot_restore_exception_caught(self, soul, tmp_path):
		"""Line 211: snapshot upload fails → exception logged, not raised."""
		snap_file = tmp_path / "work_20260101.snapshot"
		snap_file.write_bytes(b"data")

		with patch("requests.post", side_effect=Exception("upload failed")):
			soul.restore_soul(str(tmp_path), commit=True)  # Must not raise

	def test_dry_run_prints_would_restore(self, soul, tmp_path, capsys):
		"""Lines 188-189: dry run → prints would-restore messages."""
		snap_file = tmp_path / "social_20260101.snapshot"
		snap_file.write_bytes(b"data")

		soul.restore_soul(str(tmp_path), commit=False)
		captured = capsys.readouterr()
		assert "Would restore collection 'social'" in captured.out

	def test_snapshot_restore_success(self, soul, tmp_path):
		"""Lines 202-209: POST succeeds → raise_for_status passes, success logged."""
		snap_file = tmp_path / "work_20260101.snapshot"
		snap_file.write_bytes(b"data")

		mock_resp = MagicMock()
		mock_resp.raise_for_status.return_value = None
		with patch("requests.post", return_value=mock_resp):
			soul.restore_soul(str(tmp_path), commit=True)
		assert mock_resp.raise_for_status.called
