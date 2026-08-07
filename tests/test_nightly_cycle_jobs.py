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

from red_pill.jobs.recipes import load_recipe

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
	state = tmp_path / "state"
	state.mkdir()
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: state)
	return state


@pytest.mark.parametrize("name, source, priority", [("sleep", "dag_job", 8), ("chronicle", "script_job", 7)])
def test_kernel_nightly_recipes_are_valid(name, source, priority):
	"""Las recetas del kernel cargan, validan en el submit y anclan cwd al repo.

	El orden de prioridades es el contrato de la noche: sueño (8) > chronicle
	(7) > entrenamiento (5) — mayor número = más urgente. El sueño es una
	receta del `dag_job` (RFC_JOB_DAG — cada unidad del ciclo es una etapa con
	su minion); el chronicle sigue siendo `script_job`.
	"""
	from red_pill.jobs.drivers import get_driver_class

	source_loaded, payload, prio, parent, _is_seed = load_recipe(str(REPO_ROOT / "configs" / "jobs" / f"{name}.yaml"))
	assert source_loaded == source and parent is None
	assert prio == priority
	assert payload["cwd"] == str(REPO_ROOT)
	get_driver_class(source_loaded)().validate(payload)


def test_sleep_recipe_declares_dag_driver():
	"""El sueño es una receta del `dag_job`: cada unidad del ciclo es una etapa
	con su minion (sleep_ritual/sleep_phase/sleep_finalize) y la preflight GPU
	por etapa vive en el driver DAG (probe de salud real, D7)."""
	from red_pill.jobs.drivers import get_driver_class

	_, payload, _, _, _ = load_recipe(str(REPO_ROOT / "configs" / "jobs" / "sleep.yaml"))
	assert get_driver_class("dag_job") is not None
	assert "defer_exit_code" not in payload  # el deferral es nativo del driver
	assert payload["mode"] == "lazy"
	assert payload["nightly_exempt"] is True  # anti-deadlock nocturno
	stages = payload["manifest"]["stages"]
	ids = [s["id"] for s in stages]
	assert "consolidation" in ids and "finalize" in ids
	assert all(s["type"] in ("agent", "command", "compound") for s in stages)


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


def test_forge_recipe_seed_marked_in_repo():
	"""Los recipes forge del repo (configs/jobs/) son SEEDS: seed=True."""
	from red_pill.jobs.recipes import load_recipe

	roles = ("forge-triage", "forge-implementor", "forge-validator", "forge-smoke-tester",
		"forge-devils-advocate", "forge-judge", "forge-doc-anchor", "forge-qa", "forge-scout")
	for name in roles:
		_, payload, _, _, is_seed = load_recipe(str(REPO_ROOT / "configs" / "jobs" / f"{name}.yaml"))
		assert is_seed is True, f"{name} debería ser seed"
		# Los seeds no llevan modelo concreto: quedan en el default del harness.
		assert payload.get("model", "flash") == "flash"


def test_forge_config_local_overrides_seed_and_is_not_seed(tmp_path, monkeypatch):
	"""Una config local en .red-pill/jobs/ gana al seed y NO se marca como seed."""
	from red_pill.jobs.recipes import load_recipe

	# Simula una instalación: configura local que copia el seed y fija modelo real.
	ws = tmp_path / "ws"
	(ws / ".red-pill" / "jobs").mkdir(parents=True)
	local = ws / ".red-pill" / "jobs" / "forge-implementor.yaml"
	local.write_text(
		"source: agentic_job\n"
		"priority: 5\n"
		"backend: opencode\n"
		"model: opencode-go/deepseek-v4-pro\n"
		"effort: high\n",
		encoding="utf-8",
	)
	_, payload, _, _, is_seed = load_recipe("forge-implementor", base_dir=ws)
	assert is_seed is False
	assert payload["model"] == "opencode-go/deepseek-v4-pro"


def test_job_submit_mcp_blocks_agentic_without_model():
	"""Fail-safe: job_submit bloquea un job agéntico sin modelo (flash = placeholder)."""
	import asyncio

	from red_pill.mcp_server import handle_job_submit

	for bad_payload in ({}, {"prompt": "x"}, {"prompt": "x", "model": "flash"}):
		res = asyncio.run(handle_job_submit({"source": "agentic_job", "payload": bad_payload}))
		text = res[0].text
		assert "sin modelo configurado" in text or "Bloqueado" in text, text

	# Con modelo real pasa.
	res = asyncio.run(handle_job_submit({"source": "agentic_job", "payload": {"prompt": "x", "model": "opencode-go/deepseek-v4-pro"}}))
	assert "Job encolado" in res[0].text
