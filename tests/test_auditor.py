from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from red_pill.metabolism.auditor import AuditFinding, SentinelAuditor


class _FakeHealPlugin:
	name = "fake"

	def __init__(self):
		self.calls = 0

	def heal(self, cfg, finding):
		self.calls += 1
		return True


def test_heal_finding_respects_auto_heal_flag(auditor):
	"""AUTO_HEAL_ENABLED=false must keep every plugin report-only."""
	plugin = _FakeHealPlugin()
	finding = AuditFinding(type="service_down", severity=7.0, message="down")

	assert auditor._heal_finding(plugin, SimpleNamespace(AUTO_HEAL_ENABLED=False), finding) is False
	assert plugin.calls == 0

	assert auditor._heal_finding(plugin, SimpleNamespace(AUTO_HEAL_ENABLED=True), finding) is True
	assert plugin.calls == 1


def test_audit_vitals_dispatch_is_report_only(monkeypatch, auditor):
	"""The audit loop itself must not call heal when the flag is off."""
	import types

	from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

	class FakePlugin(SentinelPlugin):
		healed = 0

		@property
		def name(self):
			return "fake"

		def is_enabled(self, cfg):
			return True

		def audit(self, cfg):
			return [AuditFinding(type="fake", severity=1.0, message="find me")]

		def heal(self, cfg, finding):
			type(self).healed += 1
			return True

	module = types.ModuleType("red_pill.metabolism.sentinel_plugins.fake")
	module.FakePlugin = FakePlugin
	monkeypatch.setattr("red_pill.config.get_config", lambda: SimpleNamespace(AUTO_HEAL_ENABLED=False))
	monkeypatch.setattr("pkgutil.iter_modules", lambda path: [("fake", None, None)])
	monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""))
	monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: MagicMock())
	monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
	monkeypatch.setattr("importlib.import_module", lambda name: module)

	report = auditor.audit_vitals()
	assert FakePlugin.healed == 0
	assert any(f.type == "fake" for f in report.findings)


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

	# Bypass the differential gate so the audit body runs.
	with (
		patch.object(auditor, "_step_is_current", return_value=False),
		patch.object(auditor, "_mark_step", return_value=None),
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


def _green():
	res = MagicMock()
	res.returncode = 0
	res.stdout = ""
	return res


@patch("subprocess.run")
def test_tests_are_not_run_by_default(mock_run, auditor, monkeypatch):
	"""El timer horario no corre la suite del checkout vivo (AUDITOR_RUN_TESTS off)."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg.get_config(), "AUDITOR_RUN_TESTS", False, raising=False)
	auditor.memory_mgr = MagicMock()
	mock_run.side_effect = [_green(), _green()]

	auditor.audit_repo(".")

	cmds = [c.args[0] for c in mock_run.call_args_list]
	assert not any("pytest" in cmd for cmd in cmds)
	auditor.memory_mgr.evaporate_signals.assert_any_call("signal_test_failure")


@patch("subprocess.run")
def test_tests_run_unit_only_when_enabled(mock_run, auditor, monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg.get_config(), "AUDITOR_RUN_TESTS", True, raising=False)
	auditor.memory_mgr = MagicMock()
	mock_run.side_effect = [_green(), _green(), _green()]

	auditor.audit_repo(".")

	pytest_cmd = [c.args[0] for c in mock_run.call_args_list if "pytest" in c.args[0]][0]
	assert "--ignore=tests/integration" in pytest_cmd and "not integration" in pytest_cmd


def _git_repo(path):
	import subprocess as sp

	path.mkdir()
	for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
		sp.run(["git", "-C", str(path), *cmd], check=True)
	(path / "m.py").write_text("x = 1\n")
	sp.run(["git", "-C", str(path), "add", "."], check=True)
	sp.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
	return path


def _checks_run(mock_run):
	return [c.args[0][2] for c in mock_run.call_args_list if c.args and c.args[0][1:2] == ["run"]]


@patch("subprocess.run")
def test_unchanged_code_is_not_audited_again(mock_run, tmp_path):
	"""Sin cambios desde la última pasada completa, ruff/mypy no se repiten; un
	cambio versionado o un fichero nuevo no ignorado los vuelve a lanzar."""
	repo = _git_repo(tmp_path / "repo")
	auditor = SentinelAuditor(force=False)
	auditor.memory_mgr = MagicMock()
	auditor.cache_file = tmp_path / "auditor_cache.json"
	mock_run.return_value = _green()

	auditor.audit_repo(str(repo))
	assert _checks_run(mock_run) == ["ruff", "mypy"]

	mock_run.reset_mock()
	auditor.audit_repo(str(repo))
	assert _checks_run(mock_run) == []

	(repo / "m.py").write_text("x = 2\n")
	auditor.audit_repo(str(repo))
	assert _checks_run(mock_run) == ["ruff", "mypy"]

	mock_run.reset_mock()
	(repo / "nuevo.py").write_text("y = 1\n")
	auditor.audit_repo(str(repo))
	assert _checks_run(mock_run) == ["ruff", "mypy"]


@patch("subprocess.run")
def test_a_killed_run_only_redoes_the_unfinished_steps(mock_run, tmp_path):
	"""El caché se guarda al acabar cada paso: si la unit mata la pasada a mitad,
	la siguiente no repite lo que sí terminó."""
	repo = _git_repo(tmp_path / "repo")
	auditor = SentinelAuditor(force=False)
	auditor.memory_mgr = MagicMock()
	auditor.cache_file = tmp_path / "auditor_cache.json"
	auditor._mark_step(str(repo), "ruff", auditor._project_fingerprint(str(repo)))
	mock_run.return_value = _green()

	auditor.audit_repo(str(repo))

	assert _checks_run(mock_run) == ["mypy"]


def test_fingerprint_ignores_noise_outside_the_code(tmp_path):
	repo = _git_repo(tmp_path / "repo")
	(repo / ".gitignore").write_text("*.log\n")
	auditor = SentinelAuditor(force=False)
	fp = auditor._project_fingerprint(str(repo))
	(repo / "debug.log").write_text("ruido")
	(repo / ".venv").mkdir()
	(repo / ".venv" / "lib.py").write_text("z = 0\n")
	assert auditor._project_fingerprint(str(repo)) == fp
