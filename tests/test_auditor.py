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
	def run_side_effect(cmd, *args, **kwargs):
		cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
		res = MagicMock()
		res.returncode = 0
		if "nvidia-smi" in cmd_str:
			res.stdout = "7800,8192"
		elif "dmesg" in cmd_str or "journalctl" in cmd_str:
			res.stdout = "Out of memory: Killed process 1234 (redpill-worker)"
		else:
			res.stdout = ""
		return res

	mock_run.side_effect = run_side_effect

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
	def run_side_effect(cmd, *args, **kwargs):
		cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
		res = MagicMock()
		res.returncode = 0
		if "nvidia-smi" in cmd_str:
			res.stdout = "1024,8192"
		elif "dmesg" in cmd_str or "journalctl" in cmd_str:
			res.stdout = "System functioning normally"
		else:
			res.stdout = ""
		return res

	mock_run.side_effect = run_side_effect

	from red_pill.core.service_contract import ServiceContract

	dummy_manifest = {"dummy": ServiceContract(name="dummy", unit="dummy.service", type="oneshot", max_runtime_s=60)}
	with (
		patch("urllib.request.urlopen"),
		patch("pathlib.Path.exists", return_value=False),
		patch("red_pill.metabolism.sentinel_plugins.check_duplicate_services.load_manifest", return_value=dummy_manifest),
		# Isolate the vitals (VRAM/OOM/net) logic from the dynamically-loaded sentinel
		# plugin suite: those plugins check live services/paths (env-dependent) and are
		# covered by their own tests + the sandbox lifecycle, not by this unit. Without
		# this, the plugins fire service_down/sip_missing findings from the test's own
		# mocks (Path.exists=False, empty systemctl) and the audit can never be green.
		patch("pkgutil.iter_modules", return_value=[]),
	):
		report = auditor.audit_vitals()

	assert report.status == "green"
	assert len(report.findings) == 0


def test_audit_runtime_priority_and_file_scanning(auditor):
	# Mock units, failed, journalctl
	mock_units = MagicMock()
	mock_units.returncode = 0
	mock_units.stdout = "redpill-llm.service"

	mock_failed = MagicMock()
	mock_failed.returncode = 0
	mock_failed.stdout = ""

	mock_journal = MagicMock()
	mock_journal.returncode = 0
	mock_journal.stdout = "Normal log line\n[WARNING] connection timeout"

	# Mock file exists and file tail reading
	log_content = [
		"error: connection reset by peer",
		"llama_model_loader: loaded metadata with raise_exception"
	]

	with (
		patch("subprocess.run") as mock_run,
		patch("pathlib.Path.exists", return_value=True),
		patch("red_pill.metabolism.auditor.SentinelAuditor._read_log_tail", return_value=log_content) as mock_tail,
	):
		mock_run.side_effect = [mock_units, mock_failed, mock_journal]

		report = auditor.audit_runtime()

		# Assert journalctl was called with -p 4
		args_list = mock_run.call_args_list
		# The third call (index 2) should be the journalctl command
		journalctl_cmd = args_list[2][0][0]
		assert "-p" in journalctl_cmd
		assert "4" in journalctl_cmd

		# Assert findings were generated from the error.log traceback, but model metadata was ignored
		assert report.status == "yellow"
		assert len(report.findings) == 1
		finding = report.findings[0]
		assert finding.type == "journal"
		assert "connection reset by peer" in finding.message
		assert "llama_model_loader" not in finding.message


def test_audit_runtime_ignores_self_referential_and_loader(auditor):
	mock_units = MagicMock()
	mock_units.returncode = 0
	mock_units.stdout = "redpill-worker.service"

	mock_failed = MagicMock()
	mock_failed.returncode = 0
	mock_failed.stdout = ""

	# Journalctl logs contain self-referential auditor lines and llama model loader lines
	mock_journal = MagicMock()
	mock_journal.returncode = 0
	mock_journal.stdout = (
		"Active Pain detected: signal_journal_failure\n"
		"recent daemon errors in journal:\n"
		"llama_model_loader: loaded metadata with raise_exception"
	)

	with (
		patch("subprocess.run") as mock_run,
		patch("pathlib.Path.exists", return_value=True),
		patch("red_pill.metabolism.auditor.SentinelAuditor._read_log_tail", return_value=[]),
	):
		mock_run.side_effect = [mock_units, mock_failed, mock_journal]
		report = auditor.audit_runtime()

		# Everything should be ignored, status stays green
		assert report.status == "green"
		assert len(report.findings) == 0

