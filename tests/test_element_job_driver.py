"""Driver element_job — template MAP reanudable (N elementos, un step por elemento)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from red_pill.jobs.drivers import get_driver
from red_pill.jobs.drivers.base import JobDeferred, JobStepTimeout
from red_pill.jobs.drivers.element import ElementJobDriver


def _bind(driver: ElementJobDriver, timeout: int = 300) -> ElementJobDriver:
	driver.bind("job-1234-5678", attempts=0, step_timeout_s=timeout)
	return driver


def _payload(**overrides):
	payload = {
		"elements": ["a", "b", "c"],
		"step_command": ["echo", "process"],
		"defer_exit_code": 77,
		"cwd": "/tmp",
	}
	payload.update(overrides)
	return payload


@pytest.fixture(autouse=True)
def _no_systemd(monkeypatch):
	monkeypatch.setattr(ElementJobDriver, "_has_systemd", staticmethod(lambda: False))


def test_validate_exige_elementos_y_funcion():
	ElementJobDriver.validate(_payload())
	with pytest.raises(ValueError, match="step_command"):
		ElementJobDriver.validate({"elements": [1]})
	with pytest.raises(ValueError, match="elements"):
		ElementJobDriver.validate({"step_command": "x"})


def test_step_procesa_un_elemento_y_avanza_indice():
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		mock_run.return_value = MagicMock(returncode=0)
		out = driver.step(_payload(), {})
	assert out.completed is False
	assert out.new_checkpoint["index"] == 1 and out.new_checkpoint["total"] == 3
	assert out.progress["current"] == 1 and out.progress["percent"] == 33
	# el elemento viajó por RP_ELEMENT
	env = mock_run.call_args.kwargs["env"]
	assert env["RP_ELEMENT"] == '"a"'
	assert env["RP_ELEMENT_INDEX"] == "0"


def test_step_reanuda_desde_el_indice_del_checkpoint():
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		mock_run.return_value = MagicMock(returncode=0)
		out = driver.step(_payload(), {"index": 2, "total": 3})
	assert out.completed is True  # procesó el último (index 2) y cerró
	assert out.new_checkpoint["index"] == 3 and out.new_checkpoint["total"] == 3


def test_step_completado_sin_trabajo():
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		out = driver.step(_payload(), {"index": 3, "total": 3})
	assert out.completed is True
	mock_run.assert_not_called()


def test_elemento_defer_difiere_el_job():
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		mock_run.return_value = MagicMock(returncode=77)
		with pytest.raises(JobDeferred):
			driver.step(_payload(), {})


def test_watchdog_timeout_frustra_el_step():
	import time

	driver = _bind(ElementJobDriver(), timeout=1)
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:

		def slow_run(*a, **kw):
			time.sleep(1.1)  # supera la cota de 1s → elapsed >= 0.9s
			return MagicMock(returncode=124)

		mock_run.side_effect = slow_run
		with pytest.raises(JobStepTimeout):
			driver.step(_payload(), {})


def test_elements_command_carga_la_lista(tmp_path):
	driver = _bind(ElementJobDriver())
	payload = _payload()
	del payload["elements"]
	payload["elements_command"] = ["cat", str(tmp_path / "elems.json")]
	(tmp_path / "elems.json").write_text('["x","y"]')
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:

		def side_effect(argv, **kw):
			if argv[0] == "cat":
				return MagicMock(returncode=0, stdout='["x","y"]')
			return MagicMock(returncode=0)

		mock_run.side_effect = side_effect
		out = driver.step(payload, {})
	assert out.new_checkpoint["index"] == 1 and out.new_checkpoint["total"] == 2


def test_n_se_congela_en_el_primer_step():
	"""exactamente N: la lista se congela en el checkpoint; no se re-lee la fuente."""
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		mock_run.return_value = MagicMock(returncode=0)
		# primer step: fija lista de 3
		out = driver.step(_payload(), {})
		assert out.new_checkpoint["index"] == 1 and out.new_checkpoint["total"] == 3
		assert out.new_checkpoint["elements"] == ["a", "b", "c"]
		# step posterior: usa la lista del checkpoint (la fuente ya no se consulta)
		driver._load_elements = MagicMock(side_effect=AssertionError("no debe re-leer la fuente"))
		out2 = driver.step(_payload(), out.new_checkpoint)
		assert out2.new_checkpoint["index"] == 2
		driver._load_elements.assert_not_called()


def test_checkpoint_sin_lista_con_fuente_encogida_avisa():
	"""Un checkpoint viejo (sin lista congelada) con fuente dinámica encogida →
	error con instrucción (no repetir inestable)."""
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run"):
		driver._load_elements = MagicMock(return_value=["x", "y"])  # fuente encogida: 2
		with pytest.raises(RuntimeError, match="re-encola"):
			driver.step(_payload(), {"index": 2, "total": 3})


def test_skip_next_salta_el_elemento_y_avanza_sin_ejecutar():
	"""job_skip del operador: skip_next en el checkpoint → no ejecuta el elemento,
	avanza el índice marcándolo 'skipped' y consume la marca (no viaja al step)."""
	driver = _bind(ElementJobDriver())
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		out = driver.step(_payload(), {"index": 1, "total": 3, "elements": ["a", "b", "c"], "skip_next": True})
	mock_run.assert_not_called()  # el elemento se saltó, no se ejecutó
	assert out.completed is False
	assert out.new_checkpoint["index"] == 2 and out.new_checkpoint["total"] == 3
	assert out.new_checkpoint["skipped"] == [1]
	assert "skip_next" not in out.new_checkpoint  # la marca se consume


def test_skip_exit_code_avanza_sin_reintentar():
	"""skip_exit_code declarativo: el satélite sale con el código de skip → se
	marca 'skipped' y avanza el índice en vez de quemar un intento."""
	driver = _bind(ElementJobDriver())
	payload = _payload(skip_exit_code=79)
	with patch("red_pill.jobs.drivers.element.subprocess.run") as mock_run:
		mock_run.return_value = MagicMock(returncode=79)
		out = driver.step(payload, {"index": 0, "total": 3, "elements": ["a", "b", "c"]})
	assert out.completed is False
	assert out.new_checkpoint["index"] == 1 and out.new_checkpoint["skipped"] == [0]


def test_driver_registrado():
	assert ElementJobDriver in get_driver("element_job").__class__.__mro__
	assert ElementJobDriver.source == "element_job"


def test_validate_rechaza_payloads_invalidos(tmp_path):
	with pytest.raises(ValueError, match="step_command"):
		ElementJobDriver.validate({"elements": [1]})
	with pytest.raises(ValueError, match="elements"):
		ElementJobDriver.validate({"step_command": "x"})
	with pytest.raises(ValueError, match="elements_file no existe"):
		ElementJobDriver.validate({"step_command": "x", "elements_file": str(tmp_path / "no.json")})
	with pytest.raises(ValueError, match="124"):
		ElementJobDriver.validate({"step_command": "x", "elements": [1], "defer_exit_code": 124})


def test_preflight_llm_required_difiere():
	driver = _bind(ElementJobDriver())
	from red_pill.jobs.drivers.base import JobDeferred

	driver._llm_healthy = staticmethod(lambda port: False)
	with pytest.raises(JobDeferred):
		driver.preflight({"preflight": {"llm_required": True}})
	driver._llm_healthy = staticmethod(lambda port: True)
	driver.preflight({"preflight": {"llm_required": True}})  # no lanza


def test_load_elements_desde_fichero(tmp_path):
	driver = _bind(ElementJobDriver())
	elems = tmp_path / "elems.json"
	elems.write_text('["a","b"]')
	payload = _payload()
	del payload["elements"]
	payload["elements_file"] = str(elems)
	assert driver._load_elements(payload, str(tmp_path)) == ["a", "b"]


def test_build_argv_con_y_sin_systemd(tmp_path):
	driver = _bind(ElementJobDriver())
	driver._has_systemd = staticmethod(lambda: True)
	argv = driver._build_argv(_payload(), str(tmp_path))
	assert argv[0] == "systemd-run"
	assert "--unit=redpill-job-job-1234" in argv
	driver._has_systemd = staticmethod(lambda: False)
	argv = driver._build_argv(_payload(), str(tmp_path))
	assert argv == ["echo", "process"]


def test_build_env_expone_elemento_y_codigos():
	driver = _bind(ElementJobDriver())
	env = driver._build_env(_payload(), "/tmp", "el-elem", 3)
	assert json.loads(env["RP_ELEMENT"]) == "el-elem"
	assert env["RP_ELEMENT_INDEX"] == "3"
	assert env["RP_DEFER_EXIT_CODE"] == "77"


def test_run_command_timeout_retorna_124():
	import subprocess as sp

	driver = _bind(ElementJobDriver(), timeout=60)
	driver._has_systemd = staticmethod(lambda: False)
	with patch("red_pill.jobs.drivers.element.subprocess.run", side_effect=sp.TimeoutExpired("cmd", 60)):
		elapsed, rc = driver._run_command(_payload(), "/tmp", "x", 0)
	assert rc == 124 and elapsed >= 0


def test_template_yaml_y_recetario_existen():
	from pathlib import Path

	template = Path("configs/jobs/_TEMPLATE_element_job.yaml")
	assert template.exists()
	src = template.read_text(encoding="utf-8")
	assert "source: element_job" in src
	assert "RP_ELEMENT" in src  # el contrato por elemento está documentado

	doc = Path("docs/TECHNICAL/OPERATIONS/ELEMENT_JOB_TEMPLATE.md")
	assert doc.exists()
	assert "element_job" in doc.read_text(encoding="utf-8")
