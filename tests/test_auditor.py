from unittest.mock import MagicMock, patch

import pytest

from red_pill.metabolism.auditor import SentinelAuditor


@pytest.fixture
def auditor():
	return SentinelAuditor(force=True)


def test_audit_repo_not_found(auditor):
	report = auditor.audit_repo("/non/existent/path")
	assert report.status == "red"
	assert any(f.type == "infra" for f in report.findings)


@patch("subprocess.run")
def test_audit_repo_ruff_failure(mock_run, auditor):
	# Mock Ruff failure
	mock_ruff = MagicMock()
	mock_ruff.returncode = 1
	mock_ruff.stdout = "Found 1 error"

	# Mock Pytest success
	mock_pytest = MagicMock()
	mock_pytest.returncode = 0

	mock_run.side_effect = [mock_ruff, mock_pytest, mock_pytest]

	report = auditor.audit_repo(".")
	assert report.status == "yellow"
	assert any(f.type == "formatting" for f in report.findings)


@patch("subprocess.run")
def test_audit_repo_all_green(mock_run, auditor):
	# Mock success for both
	mock_res = MagicMock()
	mock_res.returncode = 0
	mock_run.side_effect = [mock_res, mock_res, mock_res]

	report = auditor.audit_repo(".")
	assert report.status == "green"
	assert len(report.findings) == 0
	assert report.intensity == 0.0


@patch("subprocess.run")
def test_audit_runtime_daemon_failure(mock_run, auditor):
	mock_units = MagicMock()
	mock_units.returncode = 0
	mock_units.stdout = "redpill-worker.service\nredpill-pulse.service"

	mock_failed = MagicMock()
	mock_failed.returncode = 0
	mock_failed.stdout = "redpill-worker.service"

	mock_journal = MagicMock()
	mock_journal.returncode = 0
	mock_journal.stdout = "Nov 01 12:00:00 Error: connection failed\nNov 01 12:01:00 Normal log line"

	mock_run.side_effect = [mock_units, mock_failed, mock_journal]

	with patch("pathlib.Path.exists", return_value=True):
		report = auditor.audit_runtime()
	assert report.status == "red"
	assert any(f.type == "daemon" for f in report.findings)
	assert any(f.type == "journal" for f in report.findings)


@patch("subprocess.run")
def test_audit_vitals_exhaustion(mock_run, auditor):
	mock_vram = MagicMock()
	mock_vram.returncode = 0
	mock_vram.stdout = "7800,8192"  # > 95% used

	mock_dmesg = MagicMock()
	mock_dmesg.returncode = 0
	mock_dmesg.stdout = "Out of memory: Killed process 1234 (redpill-worker)"

	mock_run.side_effect = [mock_vram, mock_dmesg]

	# We mock urllib and sqlite3 since those hit real system components
	from red_pill.core.service_contract import ServiceContract

	dummy_manifest = {"dummy": ServiceContract(name="dummy", unit="dummy.service", type="oneshot", max_runtime_s=60)}
	with (
		patch("urllib.request.urlopen"),
		patch("pathlib.Path.exists", return_value=False),
		patch("red_pill.metabolism.sentinel_plugins.check_duplicate_services.load_manifest", return_value=dummy_manifest),
	):
		report = auditor.audit_vitals()

	assert report.status == "red"
	assert any(f.type == "exhaustion" and "OOM Killer" in f.message for f in report.findings)
	assert any(f.type == "exhaustion" and "VRAM Exhaustion" in f.message for f in report.findings)


@patch("subprocess.run")
def test_audit_vitals_all_green(mock_run, auditor):
	mock_vram = MagicMock()
	mock_vram.returncode = 0
	mock_vram.stdout = "1024,8192"  # Low usage

	mock_dmesg = MagicMock()
	mock_dmesg.returncode = 0
	mock_dmesg.stdout = "System functioning normally"

	mock_run.side_effect = [mock_vram, mock_dmesg]

	from red_pill.core.service_contract import ServiceContract

	dummy_manifest = {"dummy": ServiceContract(name="dummy", unit="dummy.service", type="oneshot", max_runtime_s=60)}
	with (
		patch("urllib.request.urlopen"),
		patch("pathlib.Path.exists", return_value=False),
		patch("red_pill.metabolism.sentinel_plugins.check_duplicate_services.load_manifest", return_value=dummy_manifest),
	):
		report = auditor.audit_vitals()

	assert report.status == "green"
	assert len(report.findings) == 0
