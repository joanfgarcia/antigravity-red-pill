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
