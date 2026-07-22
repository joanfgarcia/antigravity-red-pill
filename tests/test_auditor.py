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
def test_self_heals_signal_on_pass_without_force(mock_run):
	"""Regression for the Fast-Fail deadlock: with force=False AND a signal
	already present, a passing run must still execute the real checks and
	evaporate the signals. The old code skipped the run when a signal existed,
	so a landed fix could never clear it (stuck pain signals)."""
	auditor = SentinelAuditor(force=False)
	auditor.memory_mgr = MagicMock()
	auditor.memory_mgr.has_signal.return_value = True  # signals already present

	green = MagicMock()
	green.returncode = 0
	mock_run.side_effect = [green, green, green]  # ruff, mypy, pytest all pass

	# Bypass the differential mtime gate so the audit body runs.
	with (
		patch.object(auditor, "_get_project_mtime", return_value=100.0),
		patch.object(auditor, "_get_cached_mtime", return_value=0.0),
		patch.object(auditor, "_update_cached_mtime", return_value=None),
	):
		report = auditor.audit_repo(".")

	assert report.status == "green"
	assert len(report.findings) == 0
	evaporated = {c.args[0] for c in auditor.memory_mgr.evaporate_signals.call_args_list}
	assert evaporated == {"signal_formatting_failure", "signal_typing_failure", "signal_test_failure"}


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
	log_content = ["error: connection reset by peer", "llama_model_loader: loaded metadata with raise_exception"]

	with (
		patch("subprocess.run") as mock_run,
		patch("pathlib.Path.exists", return_value=True),
		patch("red_pill.metabolism.auditor.SentinelAuditor._read_log_new_lines", return_value=log_content),
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
		"Active Pain detected: signal_journal_failure\nrecent daemon errors in journal:\nllama_model_loader: loaded metadata with raise_exception"
	)

	with (
		patch("subprocess.run") as mock_run,
		patch("pathlib.Path.exists", return_value=True),
		patch("red_pill.metabolism.auditor.SentinelAuditor._read_log_new_lines", return_value=[]),
	):
		mock_run.side_effect = [mock_units, mock_failed, mock_journal]
		report = auditor.audit_runtime()

		# Everything should be ignored, status stays green
		assert report.status == "green"
		assert len(report.findings) == 0


def test_read_log_new_lines_recency(auditor, tmp_path):
	"""A stale error must not be re-returned on later audits (byte-offset cursor)."""
	auditor.log_offsets_file = tmp_path / "offsets.json"
	log = tmp_path / "error.log"
	log.write_text("ValueError: Failed to create llama_context\n", encoding="utf-8")

	# First sight → cursor initialized at end, history NOT re-scanned.
	assert auditor._read_log_new_lines(log) == []
	# No new content → still nothing (the stale error does not re-fire).
	assert auditor._read_log_new_lines(log) == []

	# A genuinely new error appended → caught exactly once.
	with open(log, "a", encoding="utf-8") as f:
		f.write("Exception: fresh failure\n")
	assert auditor._read_log_new_lines(log) == ["Exception: fresh failure"]
	assert auditor._read_log_new_lines(log) == []


def test_read_log_new_lines_handles_truncation(auditor, tmp_path):
	"""Rotation/truncation (size shrank) resets the cursor to 0."""
	auditor.log_offsets_file = tmp_path / "offsets.json"
	log = tmp_path / "error.log"
	log.write_text("old error line\n" * 50, encoding="utf-8")
	auditor._read_log_new_lines(log)  # init cursor at end

	log.write_text("error: after truncation\n", encoding="utf-8")  # smaller than before
	assert auditor._read_log_new_lines(log) == ["error: after truncation"]
