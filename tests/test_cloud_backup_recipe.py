"""Receta promovida del backup: dag_job válido y no seed."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECIPE = REPO / "configs" / "jobs" / "cloud_backup.yaml"


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
