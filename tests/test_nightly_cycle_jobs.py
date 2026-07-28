"""Ciclos nocturnos como jobs de la cola central (migración del 28 jul 2026).

Tras el incidente de la madrugada del 28 jul (el sueño y el entrenamiento de
Bit compitiendo por la VRAM sin coordinación → 3 OOM → FRUSTRATED), sleep y
chronicle dejan de ejecutarse directamente por systemd: los timers ENCOLAN una
receta y el runner serializa. Aquí se cubren las piezas de esa migración:
recetas versionadas del kernel, propagación del auto-deferral del sueño y el
candado --singleton de los timers de calendario.
"""

import argparse
import json
import time
from pathlib import Path

import pytest

from red_pill.jobs.drivers.script import ScriptJobDriver
from red_pill.jobs.recipes import load_recipe

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
	state = tmp_path / "state"
	state.mkdir()
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: state)
	return state


@pytest.mark.parametrize("name, priority", [("sleep", 8), ("chronicle", 7)])
def test_kernel_nightly_recipes_are_valid(name, priority):
	"""Las recetas del kernel cargan, validan en el submit y anclan cwd al repo.

	El orden de prioridades es el contrato de la noche: sueño (8) > chronicle
	(7) > entrenamiento (5) — mayor número = más urgente.
	"""
	source, payload, prio, parent = load_recipe(str(REPO_ROOT / "configs" / "jobs" / f"{name}.yaml"))
	assert source == "script_job" and parent is None
	assert prio == priority
	assert payload["cwd"] == str(REPO_ROOT)
	ScriptJobDriver.validate(payload)


def test_sleep_recipe_declares_defer_contract():
	"""El sueño se auto-difiere con exit 75 (EX_TEMPFAIL): la receta debe
	declararlo para que el runner reintente en vez de dar el ciclo por bueno."""
	_, payload, _, _ = load_recipe(str(REPO_ROOT / "configs" / "jobs" / "sleep.yaml"))
	assert payload["defer_exit_code"] == 75
	assert payload["progress"]["mode"] == "single"


def test_last_cycle_deferred(isolated_state):
	from red_pill.metabolism.sleep import last_cycle_deferred

	status = isolated_state / "sleep_phase_status.json"
	assert last_cycle_deferred() is False  # sin fichero no hay deferral

	status.write_text(json.dumps({"deferred": True, "updated_at": time.time()}), encoding="utf-8")
	assert last_cycle_deferred() is True
	# El fichero de una noche ANTERIOR no cuenta como deferral del ciclo actual
	assert last_cycle_deferred(since=time.time() + 60) is False

	status.write_text(json.dumps({"deferred": False, "updated_at": time.time()}), encoding="utf-8")
	assert last_cycle_deferred() is False


def test_submit_singleton_skips_live_duplicate(tmp_path, monkeypatch):
	"""El timer de calendario re-encola a diario: --singleton cede si el job de
	ayer sigue vivo (p.ej. un sueño deferido toda la noche), y sin el flag el
	duplicado sí entra."""
	queue_dir = tmp_path / "queue"
	queue_dir.mkdir()
	monkeypatch.setattr("red_pill.core.paths.get_queue_dir", lambda: queue_dir)

	from red_pill.cli import handle_job
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	def _args(**over):
		base = dict(
			job_cmd="submit",
			recipe=None,
			source="script_job",
			payload=json.dumps({"step_command": "echo ok"}),
			priority=5,
			parent=None,
			title="Ciclo de sueño",
			singleton=True,
		)
		base.update(over)
		return argparse.Namespace(**base)

	handle_job(_args())
	handle_job(_args())  # duplicado con el primero aún PENDING: debe ceder

	pending = CognitiveQueueManager().list_tasks(statuses=["PENDING"])
	assert len([t for t in pending if t.get("title") == "Ciclo de sueño"]) == 1

	handle_job(_args(singleton=False))
	pending = CognitiveQueueManager().list_tasks(statuses=["PENDING"])
	assert len([t for t in pending if t.get("title") == "Ciclo de sueño"]) == 2
