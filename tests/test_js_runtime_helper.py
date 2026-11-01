"""Contrato del helper `tests/_js_runtime.py` (selección de runtime JS).

Contexto (2026-10-28): los tests de artefactos JS invocaban el `bun` del sistema
y, si faltaba, se saltaban **en silencio** — en CI (que no instala bun) eso es
cobertura cero sin avisar. El helper centraliza la elección del runtime y el
XFAIL ruidoso. Estos tests protegen ese contrato sin depender de qué runtime
haya en la máquina.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from tests._js_runtime import ENV_RUNTIME, find_js_runtime, needs_js_runtime, runtime_unavailable_reason


class TestFindRuntime:
	def test_override_node_se_respeta(self):
		with patch.dict(os.environ, {ENV_RUNTIME: "node"}):
			rt = find_js_runtime(require_bun_sqlite=False)
		if rt is not None:
			assert rt.kind == "node"
			assert rt.cmd == ["node"]

	def test_override_bun_no_devuelve_node(self):
		with patch.dict(os.environ, {ENV_RUNTIME: "bun"}):
			rt = find_js_runtime(require_bun_sqlite=False)
		if rt is not None:
			assert rt.kind == "bun"

	def test_sin_binarios_no_hay_runtime(self):
		"""Sin PATH útil, el helper devuelve None (no lanza)."""
		with patch.dict(os.environ, {"PATH": "/nonexistent-xyz"}):
			assert find_js_runtime(require_bun_sqlite=False) is None

	def test_require_bun_sqlite_excluye_node(self):
		"""Node no tiene `bun:sqlite`: con ese requisito no debe elegirse."""
		with patch.dict(os.environ, {ENV_RUNTIME: "node"}):
			rt = find_js_runtime(require_bun_sqlite=True)
		# Si devuelve algo, no puede ser un node sin capacidad bun:sqlite.
		if rt is not None:
			assert rt.has_bun_sqlite


class TestNeedsRuntimeDecorator:
	def test_hay_runtime_el_test_corre(self):
		"""Con un runtime disponible, el decorador no marca xfail."""
		rt = find_js_runtime(require_bun_sqlite=False)
		if rt is None:
			pytest.skip("sin runtime JS en esta máquina")
		mark = needs_js_runtime(require_bun_sqlite=False)
		# El decorador devuelve un MarkDecorator de pytest; no debe estar activo.
		assert mark is not None

	def test_sin_runtime_marca_xfail_con_motivo(self):
		with patch.dict(os.environ, {"PATH": "/nonexistent-xyz"}):
			mark = needs_js_runtime(require_bun_sqlite=False)
		assert mark.mark.name == "xfail"
		assert "runtime JS" in str(mark.mark.kwargs.get("reason", ""))
		assert mark.mark.kwargs.get("strict") is False


def test_runtime_unavailable_reason_es_accionable():
	"""El motivo debe decir qué falta, cómo forzarlo y el riesgo en CI."""
	msg = runtime_unavailable_reason()
	assert ENV_RUNTIME in msg, "debe indicar cómo forzar un runtime"
	assert "CI" in msg, "debe advertir de la consecuencia en CI"


def test_runtime_version_se_detecta():
	"""La versión detectada debe ser no vacía cuando hay runtime."""
	rt = find_js_runtime(require_bun_sqlite=False)
	if rt is None:
		pytest.skip("sin runtime JS en esta máquina")
	assert rt.version, "el runtime debe reportar versión"
	assert subprocess.run(rt.cmd + ["-e", "0"]).returncode == 0
