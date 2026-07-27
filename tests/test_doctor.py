"""Coverage boost for red_pill.metabolism.doctor — synchronous health verification."""

import json
from unittest.mock import MagicMock, patch

from red_pill.metabolism.doctor import _check_model_match, _check_timers, run_doctor


class TestCheckTimers:
	@patch("red_pill.metabolism.doctor.subprocess.run")
	def test_no_timers_installed(self, mock_run):
		mock_run.return_value = MagicMock(stdout="", returncode=0)
		result = _check_timers()
		assert len(result) == 1
		assert result[0][0] == "red"
		assert "No hay timers" in result[0][1]

	@patch("red_pill.metabolism.doctor.subprocess.run")
	def test_timer_active(self, mock_run):
		mock_run.return_value = MagicMock(stdout="redpill-sleep.timer loaded active running\n", returncode=0)
		result = _check_timers()
		assert result == []

	@patch("red_pill.metabolism.doctor.subprocess.run")
	def test_timer_inactive(self, mock_run):
		mock_run.return_value = MagicMock(stdout="redpill-sleep.timer loaded inactive dead\n", returncode=0)
		result = _check_timers()
		assert len(result) == 1
		assert result[0][0] == "red"
		assert "inactive" in result[0][1]

	@patch("red_pill.metabolism.doctor.subprocess.run")
	def test_timer_missing_active_field(self, mock_run):
		mock_run.return_value = MagicMock(stdout="redpill-sleep.timer loaded\n", returncode=0)
		result = _check_timers()
		assert len(result) == 1
		assert result[0][0] == "red"

	@patch("red_pill.metabolism.doctor.subprocess.run")
	def test_subprocess_exception(self, mock_run):
		mock_run.side_effect = OSError("systemctl not found")
		result = _check_timers()
		assert len(result) == 1
		assert result[0][0] == "yellow"


class TestCheckModelMatch:
	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_no_llm_running(self, mock_getenv, mock_run):
		mock_run.return_value = MagicMock(stdout="")
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry:
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert len(result) == 1
			assert result[0][0] == "info"

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_no_profile_returns_yellow(self, mock_getenv, mock_run):
		mock_run.return_value = MagicMock(stdout="")
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry:
			mock_registry.get_profile.return_value = {}
			result = _check_model_match()
			assert len(result) == 1
			assert result[0][0] == "yellow"

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_model_mismatch_native(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout="12345 llama-server --model /models/wrong.gguf\n"),
			MagicMock(stdout=""),
		]
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry:
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert any(r[0] == "red" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_model_match_native(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout="12345 llama-server --model /models/test.gguf\n"),
			MagicMock(stdout=""),
		]
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry:
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert not any(r[0] == "red" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_dual_bind_match(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"data": [{"id": "test.gguf"}]}).encode()
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry, patch("urllib.request.urlopen", return_value=mock_response):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert not any(r[0] == "red" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_dual_bind_mismatch(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"data": [{"id": "wrong.gguf"}]}).encode()
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry, patch("urllib.request.urlopen", return_value=mock_response):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert any(r[0] == "red" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_dual_bind_empty_data(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"data": []}).encode()
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry, patch("urllib.request.urlopen", return_value=mock_response):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert any(r[0] == "yellow" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_dual_bind_connection_error(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		with (
			patch("red_pill.core.model_registry.ModelRegistry") as mock_registry,
			patch("urllib.request.urlopen", side_effect=ConnectionError("refused")),
		):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert any(r[0] == "yellow" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_model_not_in_running_string(self, mock_getenv, mock_run):
		mock_run.side_effect = [
			MagicMock(stdout="12345 llama-server --model /other.gguf\n"),
			MagicMock(stdout=""),
		]
		with patch("red_pill.core.model_registry.ModelRegistry") as mock_registry:
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert any(r[0] == "red" for r in result)

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_general_exception(self, mock_getenv, mock_run):
		mock_run.side_effect = [RuntimeError("boom"), MagicMock(stdout="")]
		result = _check_model_match()
		assert any(r[0] == "yellow" for r in result)


class TestRunDoctor:
	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_green_status(self, mock_plugins, mock_timers, mock_model):
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = []
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 0

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_yellow_status(self, mock_plugins, mock_timers, mock_model):
		finding = MagicMock()
		finding.severity = 5.0
		finding.type = "warning"
		finding.message = "something yellow"
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = [finding]
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 0

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_red_status_returns_1(self, mock_plugins, mock_timers, mock_model):
		finding = MagicMock()
		finding.severity = 9.0
		finding.type = "critical"
		finding.message = "something red"
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = [finding]
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 1

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_audit_runtime_crash(self, mock_plugins, mock_timers, mock_model):
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.side_effect = RuntimeError("crash")
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 1

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[("red", "no timers")])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_red_from_timers(self, mock_plugins, mock_timers, mock_model):
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = []
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 1

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[("info", "model ok")])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_quiet_hides_infos(self, mock_plugins, mock_timers, mock_model):
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = []
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 0

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_red_from_plugins(self, mock_plugins, mock_timers, mock_model):
		mock_plugins.return_value = [("amnesia", 10.0, "Qdrant unreachable")]
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = []
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 1

	@patch("red_pill.metabolism.doctor._check_model_match", return_value=[("red", "model mismatch")])
	@patch("red_pill.metabolism.doctor._check_timers", return_value=[])
	@patch("red_pill.metabolism.doctor._audit_plugins_no_heal", return_value=[])
	def test_red_from_model(self, mock_plugins, mock_timers, mock_model):
		mock_auditor = MagicMock()
		mock_auditor.audit_runtime.return_value.findings = []
		with patch("red_pill.metabolism.auditor.SentinelAuditor", return_value=mock_auditor):
			assert run_doctor(quiet=True) == 1
