"""Receta viva del backup: dag_job válido y no seed."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECIPE = REPO / ".red-pill" / "jobs" / "cloud_backup.yaml"


@pytest.mark.skipif(not RECIPE.exists(), reason="receta live no presente (se promueve al repo tras verificar)")
def test_cloud_backup_recipe_valida_y_es_hijo_manual():
	from red_pill.jobs.drivers import get_driver_class
	from red_pill.jobs.recipes import load_recipe

	source, payload, priority, parent, is_seed = load_recipe(str(RECIPE))
	assert source == "dag_job"
	assert is_seed is False
	assert priority == 3
	get_driver_class("dag_job").validate(payload)
	stages = payload["manifest"]["stages"]
	assert [stage["id"] for stage in stages] == ["create", "upload"]
	assert stages[1]["depends_on"] == ["create"]
	assert stages[0]["type"] == "command"
