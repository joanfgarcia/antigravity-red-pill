"""El inventario del YAML no puede desfasarse del código (RFC-OBS-005 §4.1).

Los nombres de señal son un hecho del emisor; el YAML es la superficie visible.
Si alguien añade una señal y olvida regenerar, o borra un plugin y deja su
nombre como fantasma, este test lo caza.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
	return subprocess.run(
		[sys.executable, str(ROOT / "scripts" / "signal_inventory.py"), *args],
		capture_output=True,
		text=True,
		cwd=ROOT,
	)


def test_el_yaml_esta_al_dia():
	result = _run("--check")
	assert result.returncode == 0, result.stderr
	assert "al día" in result.stdout


def test_los_segmentos_declaran_sus_nombres():
	from red_pill.metabolism.auditor import REPO_STEP_SIGNAL_NAMES, SEGMENT_SIGNAL_NAMES, signal_name_for

	assert set(SEGMENT_SIGNAL_NAMES) == {"repo", "runtime", "vitals"}
	assert all(name.startswith("signal_") and name.endswith("_failure") for name in SEGMENT_SIGNAL_NAMES["repo"])
	assert set(REPO_STEP_SIGNAL_NAMES) == {"ruff", "mypy", "tests"}
	assert signal_name_for("test") == "signal_test_failure"


def test_el_bloque_generado_tiene_los_plugins():
	from scripts.signal_inventory import plugin_inventory

	plugins = plugin_inventory()
	assert "service_base" in plugins
	assert "signal_service_down_failure" in plugins["service_base"]
