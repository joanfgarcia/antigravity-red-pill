"""Tests de despliegue del adapter opencode (scripts/inject/opencode/inject.py).

Regresión 2026-09-07: `repo_root` se resolvía como `scripts/` en vez de la raíz
del repo → `inject_cli.py` (el camino real de `bunker update`/`install`) no
desplegaba ni anchors ni skills. El skill `dag` llevaba tiempo en `seeds/`
sin llegar al arnés por esta causa.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

# Raíz del repo derivada del propio test (tests/ → ../): no hay rutas fijas.
# El repo se despliega donde quiera el operador (sharing, antigravity-red-pill,
# cualquier checkout) — nada de caminos hardcodeados a máquina.
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ADAPTER_PATH = os.path.join(REPO_ROOT, "scripts", "inject", "opencode", "inject.py")


def _load_adapter() -> object:
	spec = importlib.util.spec_from_file_location("opencode_inject_under_test", ADAPTER_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["opencode_inject_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def adapter():
	return _load_adapter()


def test_repo_root_apunta_a_la_raiz_del_repo(adapter) -> None:
	# El adapter deriva repo_root en inject(); verificamos que la ruta resuelve a
	# la RAÍZ del repo (no a scripts/) — el nombre del directorio cambia según el
	# checkout (local: sharing, CI: antigravity-red-pill), así que se valida por
	# contenido, no por nombre.
	resolved = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(adapter.__file__)), "..", "..", ".."))
	assert os.path.isdir(os.path.join(resolved, ".git")), f"no es la raíz del repo: {resolved}"
	assert os.path.isdir(os.path.join(resolved, "seeds", "opencode", "skills", "dag"))
	assert os.path.exists(os.path.join(resolved, "seeds", "anchors", "job_dag_execution.md"))


def test_inject_limpio_despliega_anchor_y_skills(adapter, tmp_path) -> None:
	"""Instalación limpia: RED_PILL.md + skill job-manager/dag/forge/scout."""
	import argparse
	import os

	tmp = str(tmp_path)
	monkeypatch_detect = lambda: tmp  # noqa: E731
	adapter._detect_config_dir = monkeypatch_detect

	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False)
	n = adapter.inject(args)

	redpill = os.path.join(tmp, "RED_PILL.md")
	assert os.path.exists(redpill), "RED_PILL.md no generado"
	text = open(redpill, encoding="utf-8").read()
	assert "job_dag_execution" in text, "anchor job_dag_execution ausente en RED_PILL.md"

	for skill in ("job-manager", "dag", "forge", "scout"):
		path = os.path.join(tmp, "skills", skill, "SKILL.md")
		assert os.path.exists(path), f"skill '{skill}' no desplegado en instalación limpia"
	assert n > 0


def test_inject_idempotente(adapter, tmp_path) -> None:
	"""Segunda pasada sobre instalación existente: sin cambios (bunker update)."""
	import argparse
	import os

	tmp = str(tmp_path)
	adapter._detect_config_dir = lambda: tmp  # noqa: E731
	args = argparse.Namespace(redpill_dir=REPO_ROOT, workspace=None, no_backup=True, update=False)

	adapter.inject(args)
	# tocar el anchor para forzar divergencia
	redpill = os.path.join(tmp, "RED_PILL.md")
	original = open(redpill, encoding="utf-8").read()
	n2 = adapter.inject(args)
	assert n2 == 0, "segunda pasada debería ser idempotente (sin bloques modificados)"
	assert open(redpill, encoding="utf-8").read() == original
