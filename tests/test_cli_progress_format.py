"""`_format_progress` pinta el sub-progreso del fan-out (`stage_*`) — RFC-JOBDAG-002 Fase 3.

El driver emite `stage_label`/`stage_current`/`stage_total` para el grupo de
fan-out; la columna PROGRESS del `job list` los renderiza como "· sesión k/N".
"""

from __future__ import annotations

from red_pill.cli import _format_progress


def test_stage_fields_render():
	text = _format_progress({"current": 5, "total": 23, "percent": 22, "stage_label": "sesión", "stage_current": 3, "stage_total": 20})
	assert "5/23" in text and "22%" in text
	assert "sesión 3/20" in text


def test_sin_total_no_inventa_porcentaje():
	# sin total conocido: contador honesto, sin porcentaje fabricado
	assert _format_progress({"current": 7}) == "7"


def test_fanout_progress_del_driver_se_renderiza():
	# forma exacta que emite el driver (current/total/percent + stage_*)
	progress = {"current": 3, "total": 4, "percent": 75, "stage_label": "sesión", "stage_current": 2, "stage_total": 3}
	assert "sesión 2/3" in _format_progress(progress)
