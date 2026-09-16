"""Fase 4 §5.2/5.3: nightly.yaml (mega-ciclo chronicle → sleep) + instalador de timers."""

from __future__ import annotations

from pathlib import Path

import yaml

from red_pill.jobs.drivers.dag import DagJobDriver


def test_nightly_yaml_is_valid_dag_job():
	payload = yaml.safe_load(Path("configs/jobs/nightly.yaml").read_text(encoding="utf-8"))
	assert payload["source"] == "dag_job"
	assert payload["mission_id"] == "nightly-cycle"
	DagJobDriver.validate(payload)  # lanza si la estructura es inválida


def test_nightly_composes_chronicle_then_sleep():
	payload = yaml.safe_load(Path("configs/jobs/nightly.yaml").read_text(encoding="utf-8"))
	stages = payload["manifest"]["stages"]
	ids = [s["id"] for s in stages]
	assert ids == ["chronicle", "sleep"]
	for s in stages:
		assert s["type"] == "dag"
		assert s["on_fail"] == "warn"  # nunca bloquea el ciclo
	assert stages[1]["depends_on"] == ["chronicle"]  # orden correcto (Fase 4 §5.1)


def test_composed_recipes_exist_on_disk():
	payload = yaml.safe_load(Path("configs/jobs/nightly.yaml").read_text(encoding="utf-8"))
	for s in payload["manifest"]["stages"]:
		recipe = Path(f"configs/jobs/{s['recipe']}.yaml")
		assert recipe.exists(), f"receta {s['recipe']} debe existir como unidad manual"
		sub = yaml.safe_load(recipe.read_text(encoding="utf-8"))
		assert sub["source"] == "dag_job"


def test_schedule_pulse_installs_nightly_not_individuals():
	script = Path(__file__).resolve().parent.parent / "scripts" / "schedule_pulse.py"
	src = script.read_text(encoding="utf-8")
	# registra el nightly
	assert "NIGHTLY_RECIPE" in src
	assert "redpill-nightly.timer" in src
	assert "redpill-nightly.service" in src
	# no reinstala los pulsos individuales como unidades de calendario nuevas
	assert "_write_calendar_timer(SLEEP_TIMER" not in src
	assert "_write_calendar_timer(CHRONICLE_TIMER" not in src
	assert "disable" in src  # migración: retira los individuales


def test_sleep_integrates_memento_reinforce_stage():
	"""Fase 4 §4.2/§4.3: el refuerzo Memento-consciente es una etapa del sueño."""
	payload = yaml.safe_load(Path("configs/jobs/sleep.yaml").read_text(encoding="utf-8"))
	stages = payload["manifest"]["stages"]
	ids = [s["id"] for s in stages]
	assert "memento-reinforce" in ids
	stage = next(s for s in stages if s["id"] == "memento-reinforce")
	assert stage["type"] == "command"
	assert "memento_reinforce.py" in stage["command"]
	assert stage["on_fail"] == "warn"
	assert stage["depends_on"] == ["finalize"]
	assert Path("scripts/memento_reinforce.py").exists()
