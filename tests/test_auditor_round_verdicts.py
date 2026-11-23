"""El veredicto de un paso se firma en la ronda, no repo a repo.

Un repo limpio no puede enterrar el dolor que otro repo de la misma ronda acaba
de emitir (`_audit_ruff` evaporaba dentro del pase de cada repo). Sin veredicto
de algún repo —caído o saltado— no hay borrado.
"""

from unittest.mock import MagicMock, patch

import pytest

from red_pill.metabolism.auditor import SentinelAuditor


def _result(returncode: int = 0, stdout: str = "") -> MagicMock:
	res = MagicMock()
	res.returncode = returncode
	res.stdout = stdout
	return res


def _checks(verdicts: dict) -> object:
	"""subprocess.run falso: `verdicts[cwd][step]` → returncode."""

	def fake_run(command, **kwargs):
		step = command[2]
		cwd = kwargs.get("cwd")
		code = verdicts.get(cwd, {}).get(step, 0)
		return _result(code, "F401 bad.py:1:8 `os` imported but unused" if code else "")

	return fake_run


@pytest.fixture
def no_tests(monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg.get_config(), "AUDITOR_RUN_TESTS", False, raising=False)


def _auditor(tmp_path, repos, force=True):
	auditor = SentinelAuditor(target_repos=repos, force=force)
	auditor.memory_mgr = MagicMock()
	auditor.cache_file = tmp_path / "auditor_cache.json"
	auditor.log_offsets_file = tmp_path / "offsets.json"
	return auditor


def _evaporated(auditor):
	return [c.args[0] for c in auditor.memory_mgr.evaporate_signals.call_args_list]


@patch("subprocess.run")
def test_repo_limpio_no_cura_el_fallo_de_otro_repo(mock_run, tmp_path, no_tests):
	repo_a, repo_b = str(tmp_path / "a"), str(tmp_path / "b")
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	mock_run.side_effect = _checks({repo_a: {"ruff": 1}})

	auditor = _auditor(tmp_path, [repo_a, repo_b])
	auditor.audit_repo(repo_a)
	assert "signal_formatting_failure" not in _evaporated(auditor)

	auditor.audit_repo(repo_b)
	evaporated = _evaporated(auditor)
	assert "signal_formatting_failure" not in evaporated
	# mypy pasó en los dos: ese dolor sí se entierra, una sola vez.
	assert evaporated.count("signal_typing_failure") == 1


@patch("subprocess.run")
def test_orden_inverso_tampoco_cura(mock_run, tmp_path, no_tests):
	repo_a, repo_b = str(tmp_path / "a"), str(tmp_path / "b")
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	mock_run.side_effect = _checks({repo_a: {"ruff": 1}})

	auditor = _auditor(tmp_path, [repo_b, repo_a])
	auditor.audit_repo(repo_b)
	auditor.audit_repo(repo_a)

	assert "signal_formatting_failure" not in _evaporated(auditor)


@patch("subprocess.run")
def test_todos_limpios_entierran_una_vez(mock_run, tmp_path, no_tests):
	repo_a, repo_b = str(tmp_path / "a"), str(tmp_path / "b")
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	mock_run.side_effect = _checks({})

	auditor = _auditor(tmp_path, [repo_a, repo_b])
	auditor.audit_repo(repo_a)
	auditor.audit_repo(repo_b)
	evaporated = _evaporated(auditor)

	assert evaporated.count("signal_formatting_failure") == 1
	assert evaporated.count("signal_typing_failure") == 1
	assert evaporated.count("signal_test_failure") == 1


@patch("subprocess.run")
def test_sin_veredicto_no_hay_borrado(mock_run, tmp_path, no_tests):
	repo_a, repo_b = str(tmp_path / "a"), str(tmp_path / "b")
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	mock_run.side_effect = _checks({})

	auditor = _auditor(tmp_path, [repo_a, repo_b])
	auditor.audit_repo(repo_a)  # B no llegó a auditarse (unit caída a mitad)
	auditor.close_round([repo_a, repo_b])

	assert "signal_formatting_failure" not in _evaporated(auditor)


@patch("subprocess.run")
def test_paso_saltado_preserva_la_senal(mock_run, tmp_path, no_tests):
	repo_a, repo_b = str(tmp_path / "a"), str(tmp_path / "b")
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	mock_run.side_effect = _checks({})

	auditor = _auditor(tmp_path, [repo_a, repo_b], force=False)
	auditor.audit_repo(repo_a)
	# B no cambió desde su última pasada: ruff/mypy saltados → su veredicto no
	# existe y la señal no se puede enterrar.
	with (
		patch.object(auditor, "_step_is_current", return_value=True),
	):
		auditor.audit_repo(repo_b)

	assert "signal_formatting_failure" not in _evaporated(auditor)


@patch("subprocess.run")
def test_un_solo_repo_limpio_se_cura_como_antes(mock_run, tmp_path, no_tests):
	repo = str(tmp_path / "solo")
	(tmp_path / "solo").mkdir()
	mock_run.side_effect = _checks({})

	auditor = _auditor(tmp_path, [])
	auditor.audit_repo(repo)
	evaporated = _evaporated(auditor)

	assert evaporated.count("signal_formatting_failure") == 1
	assert evaporated.count("signal_typing_failure") == 1


@patch("subprocess.run")
def test_repo_inexistente_bloquea_el_borrado(mock_run, tmp_path, no_tests):
	repo_a = str(tmp_path / "a")
	(tmp_path / "a").mkdir()
	missing = str(tmp_path / "no-existe")
	mock_run.side_effect = _checks({})

	auditor = _auditor(tmp_path, [repo_a, missing])
	auditor.audit_repo(repo_a)
	auditor.audit_repo(missing)

	assert "signal_formatting_failure" not in _evaporated(auditor)
