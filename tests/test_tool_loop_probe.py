"""Tests del grader del bucle de herramientas (RFC-HARNESS-001 · W3).

El bug que estos tests cierran: el grader anterior aprobaba una respuesta que
inventaba un fichero, porque sólo buscaba `"foo"` o `"bar"` en el texto y las
herramientas ignoraban la ruta. Un grader que no puede fallar no es un grader.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "scripts" / "tool_loop_probe.py"


def _load():
	spec = importlib.util.spec_from_file_location("tool_loop_probe", PROBE)
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	sys.modules["tool_loop_probe"] = mod
	spec.loader.exec_module(mod)
	return mod


probe = _load()


def test_herramientas_son_conscientes_de_la_ruta():
	# El bug original: read_file devolvía a.py para cualquier path.
	assert "async def foo" in probe._read_file("src/a.py", probe.FS)
	assert "async def foo" not in probe._read_file("src/b.js", probe.FS)
	assert "(no existe" in probe._read_file("src/zzz.py", probe.FS)


def test_grep_no_se_traga_el_async_del_senuelo():
	salida = probe._grep("async", "src/", probe.FS)
	assert "src/a.py" in salida
	assert "src/c.py" in salida
	assert "src/b.js" not in salida  # b.js define foo, pero en síncrono


def test_list_dir_lista_los_tres_ficheros():
	salida = probe._list_dir("src", probe.FS)
	for esperado in ("src/a.py", "src/b.js", "src/c.py"):
		assert esperado in salida


def test_A_aprueba_la_respuesta_correcta():
	ok, motivo = probe.grade_a("Hay 2 funciones async: src/a.py y src/c.py. b.js no tiene ninguna.")
	assert ok, motivo


def test_A_rechaza_la_respuesta_que_el_bench_aprobo():
	"""La respuesta real del 2026-11-16 inventaba b.js y contaba 3."""
	ok, motivo = probe.grade_a(probe.RESPUESTA_FALSA_A)
	assert not ok, f"el grader sigue aprobando una respuesta falsa: {motivo}"


def test_B_aprueba_dos_y_rechaza_tres():
	assert probe.grade_b("Hay 2 funciones async.")[0]
	assert not probe.grade_b("Hay 3 funciones async.")[0]


def test_C_aprueba_si_y_rechaza_no():
	assert probe.grade_c("Sí, contiene una función async.")[0]
	assert not probe.grade_c("No contiene funciones async.")[0]
	assert not probe.grade_c("No hay ninguna función async.")[0]


def test_fixture_envenenado_es_distinto_del_sano():
	"""El control negativo sólo sirve si el veneno cambia el contenido."""
	assert probe.FS_ENVENENADO != probe.FS
	assert probe.FS_ENVENENADO["src/a.py"] == probe.FS["src/c.py"]


def test_control_negativo_pasa_sin_modelo():
	assert probe.control_negativo() == 0
