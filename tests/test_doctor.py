"""Coverage boost for red_pill.metabolism.doctor — synchronous health verification."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from red_pill.metabolism.doctor import _as_epoch, _check_coro, _check_model_match, _check_timers, run_doctor


class TestAsEpoch:
	"""`created_at` del outbox llega como TEXT de SQLite (UTC) o como epoch REAL."""

	def test_epoch_float(self):
		assert _as_epoch(1793600296.88) == 1793600296.88

	def test_epoch_string(self):
		assert _as_epoch("1793600296.88") == 1793600296.88

	def test_texto_sqlite_es_utc(self):
		got = _as_epoch("2026-11-01 20:27:13")
		assert got == datetime(2026, 11, 1, 20, 27, 13, tzinfo=timezone.utc).timestamp()

	def test_texto_iso_con_zona(self):
		got = _as_epoch("2026-11-01T20:27:13+00:00")
		assert got == datetime(2026, 11, 1, 20, 27, 13, tzinfo=timezone.utc).timestamp()

	def test_basura_devuelve_none(self):
		assert _as_epoch("ayer por la tarde") is None
		assert _as_epoch("") is None
		assert _as_epoch(None) is None


def _neon_db(tmp_path, created_at: str, status: str = "PENDING", with_dead_letters: bool = True):
	db = tmp_path / "neon_link.db"
	con = sqlite3.connect(db)
	con.execute("CREATE TABLE outbox (id INTEGER PRIMARY KEY, channel TEXT, status TEXT, created_at TEXT)")
	con.execute("INSERT INTO outbox (channel, status, created_at) VALUES ('soul', ?, ?)", (status, created_at))
	if with_dead_letters:
		con.execute("CREATE TABLE dead_letters (id INTEGER PRIMARY KEY, channel TEXT)")
	con.commit()
	con.close()
	return db


class TestCoroOutbox:
	"""El canal soul se audita de verdad: antes, un created_at TEXT lo cegaba entero."""

	def _run(self, tmp_path, db):
		with (
			patch("red_pill.core.paths.get_session_db", return_value=tmp_path / "sin_session.db"),
			patch("red_pill.core.paths.get_neon_link_db_path", return_value=db),
			patch("red_pill.core.paths.get_harness_config_path", return_value=tmp_path / "sin_hook.js"),
			patch("importlib.metadata.version", return_value="0.7.1"),
		):
			return _check_coro()

	def test_created_at_texto_viejo_avisa(self, tmp_path):
		stamp = datetime.now(timezone.utc) - timedelta(hours=2)
		db = _neon_db(tmp_path, stamp.strftime("%Y-%m-%d %H:%M:%S"))
		result = self._run(tmp_path, db)
		assert any(r[0] == "yellow" and "PENDING" in r[1] for r in result), result
		assert not any("No se pudo revisar el outbox soul" in r[1] for r in result)

	def test_created_at_texto_reciente_no_avisa(self, tmp_path):
		stamp = datetime.now(timezone.utc)
		db = _neon_db(tmp_path, stamp.strftime("%Y-%m-%d %H:%M:%S"))
		result = self._run(tmp_path, db)
		assert not any("PENDING" in r[1] for r in result), result

	def test_created_at_ilegible_avisa_sin_reventar(self, tmp_path):
		db = _neon_db(tmp_path, "ayer por la tarde")
		result = self._run(tmp_path, db)
		assert any(r[0] == "info" and "edad desconocida" in r[1] for r in result), result

	def test_sin_dead_letters_no_ciega_el_resto(self, tmp_path):
		stamp = datetime.now(timezone.utc) - timedelta(hours=3)
		db = _neon_db(tmp_path, stamp.strftime("%Y-%m-%d %H:%M:%S"), with_dead_letters=False)
		result = self._run(tmp_path, db)
		assert any("PENDING" in r[1] for r in result), result
		assert any("dead letters" in r[1] for r in result), result


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


	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value="samantha")
	def test_dual_bind_no_residente_no_es_red(self, mock_getenv, mock_run):
		"""El proxy carga on-demand: un modelo no residente no es un mismatch."""
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"data": [{"id": "wrong.gguf", "loaded": False}]}).encode()
		with (
			patch("red_pill.core.model_registry.ModelRegistry") as mock_registry,
			patch("urllib.request.urlopen", return_value=mock_response),
		):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert not any(r[0] == "red" for r in result), result
			assert any("on-demand" in r[1] for r in result), result

	@patch("red_pill.metabolism.doctor.subprocess.run")
	@patch("red_pill.metabolism.doctor.os.getenv", return_value=None)
	def test_perfil_no_declarado_avisa_pero_no_acusa(self, mock_getenv, mock_run):
		"""Sin MINION_PROFILE comparamos contra un default asumido: yellow, no red."""
		mock_run.side_effect = [
			MagicMock(stdout=""),
			MagicMock(stdout="12345 python run_dual_bind.py\n"),
		]
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"data": [{"id": "wrong.gguf"}]}).encode()
		with (
			patch("red_pill.core.model_registry.ModelRegistry") as mock_registry,
			patch("urllib.request.urlopen", return_value=mock_response),
		):
			mock_registry.get_profile.return_value = {"model_path": "/models/test.gguf"}
			result = _check_model_match()
			assert not any(r[0] == "red" for r in result), result
			assert any(r[0] == "yellow" and "MINION_PROFILE" in r[1] for r in result), result


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


class TestMementoRawCoverage:
	"""El raw es la base para regenerar todo (2026-11-02): una sesión sin raw no está respaldada."""

	def _registry(self, monkeypatch, root, sessions):
		class FakeRegistry:
			def __init__(self, path=None):
				self.state = {"registry": sessions}

		monkeypatch.setattr("red_pill.memento.get_memento_root", lambda: root)
		monkeypatch.setattr("red_pill.memento.registry.MementoRegistry", FakeRegistry)

	def test_sesion_sin_raw_es_rojo(self, tmp_path, monkeypatch):
		from red_pill.metabolism.doctor import _check_memento_raw

		(tmp_path / "2026-10/opencode/s1/memento").mkdir(parents=True)
		self._registry(monkeypatch, tmp_path, {"opencode": {"opencode:s1": {"dir": "2026-10/opencode/s1"}}})
		out = _check_memento_raw()
		assert out[0][0] == "red" and "sin copia raw" in out[0][1]

	def test_con_raw_es_info(self, tmp_path, monkeypatch):
		from red_pill.metabolism.doctor import _check_memento_raw

		raw = tmp_path / "2026-10/opencode/s1/raw"
		raw.mkdir(parents=True)
		(raw / "raw.json").write_text("{}", encoding="utf-8")
		self._registry(monkeypatch, tmp_path, {"opencode": {"opencode:s1": {"dir": "2026-10/opencode/s1"}}})
		out = _check_memento_raw()
		assert out[0][0] == "info"

	def test_reconstruida_cuenta_pero_se_declara(self, tmp_path, monkeypatch):
		from red_pill.metabolism.doctor import _check_memento_raw

		raw = tmp_path / "2026-05/telegram/s1/raw"
		raw.mkdir(parents=True)
		(raw / "reconstructed.md").write_text("derivado", encoding="utf-8")
		self._registry(monkeypatch, tmp_path, {"telegram": {"telegram:s1": {"dir": "2026-05/telegram/s1"}}})
		out = _check_memento_raw()
		assert out[0][0] == "info" and "no verbatim" in out[0][1]
