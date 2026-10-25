"""Retención de artefactos de estado y scratch de arneses (Janitor).

Cubre los dos huecos que no limpiaba el barrido nocturno:
- `state/external_turns/archive` (B-01h) y `state/jobs/results` (S5);
- scratch de arneses fuera de `${RP_TMP_DIR}` (p. ej. `/tmp/opencode`).
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from red_pill.swarm.agents.janitor import discover_plugins
from red_pill.swarm.agents.janitor_plugins.harness_scratch_purge import HarnessScratchPurgePlugin
from red_pill.swarm.agents.janitor_plugins.state_artifacts_purge import StateArtifactsPurgePlugin


def _janitor():
	janitor = MagicMock()
	janitor.log = MagicMock()
	return janitor


def _old(path: Path, days: int = 40) -> None:
	stamp = (datetime.now() - timedelta(days=days)).timestamp()
	os.utime(path, (stamp, stamp))


@pytest.fixture
def state(tmp_path, monkeypatch):
	from red_pill.core import paths

	root = tmp_path / "state"
	(root / "external_turns" / "archive").mkdir(parents=True)
	(root / "external_turns" / "current").mkdir(parents=True)
	(root / "jobs" / "results").mkdir(parents=True)
	monkeypatch.setattr(paths, "get_state_dir", lambda: root)
	return root


def test_descubre_los_plugins_nuevos():
	names = {plugin.name for plugin in discover_plugins()}
	assert {"state_artifacts_purge", "harness_scratch_purge"} <= names


def test_state_artifacts_purga_journal_viejo_y_respeta_current(state):
	cfg = {"plugins": {"state_artifacts_purge": {"days_to_keep": 30}}}
	old = state / "external_turns" / "archive" / "old.json"
	old.write_text("{}", encoding="utf-8")
	_old(old)
	recent = state / "external_turns" / "archive" / "recent.json"
	recent.write_text("{}", encoding="utf-8")
	pending = state / "external_turns" / "current" / "pending.json"
	pending.write_text("{}", encoding="utf-8")
	_old(pending)

	res = asyncio.run(StateArtifactsPurgePlugin().execute(_janitor(), cfg))

	assert not old.exists()
	assert recent.exists()
	assert pending.exists(), "current/ es el turno en vuelo: nunca se toca"
	assert res["journal_archived_purged"] == 1


def test_state_artifacts_conserva_activos_y_ultimo_por_mision(state, monkeypatch):
	from red_pill.cognitive import queue_manager as qm_mod

	statuses = {
		"done-new": "COMPLETED",
		"done-old": "COMPLETED",
		"active": "PROCESSING",
	}

	class FakeQM:
		def get_task(self, job_id):
			return {"status": statuses.get(job_id)}

	monkeypatch.setattr(qm_mod, "CognitiveQueueManager", FakeQM)

	results = state / "jobs" / "results"
	payloads = {
		"done-new": {"job_id": "done-new", "mission_id": "m1", "completed_at": 200.0},
		"done-old": {"job_id": "done-old", "mission_id": "m1", "completed_at": 100.0},
		"active": {"job_id": "active", "mission_id": "m1", "completed_at": 50.0},
	}
	for job_id, data in payloads.items():
		path = results / f"{job_id}.json"
		path.write_text(json.dumps(data), encoding="utf-8")
		_old(path)
	recent = results / "recent.json"
	recent.write_text(json.dumps({"job_id": "recent", "mission_id": "m1"}), encoding="utf-8")

	cfg = {"plugins": {"state_artifacts_purge": {"days_to_keep": 30, "jobs_results_keep_per_mission": 1}}}
	res = asyncio.run(StateArtifactsPurgePlugin().execute(_janitor(), cfg))

	assert (results / "done-new.json").exists(), "el más reciente de la misión se conserva"
	assert not (results / "done-old.json").exists()
	assert (results / "active.json").exists(), "un job no terminal puede reanudarse"
	assert recent.exists(), "más nuevo que la retención: intacto"
	assert res["job_results_purged"] == 1
	assert res["job_results_skipped_active"] == 1
	assert res["job_results_kept"] == 1


def test_harness_scratch_purga_hijos_viejos(tmp_path):
	scratch = tmp_path / "harness"
	scratch.mkdir()
	old_file = scratch / "old.txt"
	old_file.write_text("x", encoding="utf-8")
	_old(old_file)
	old_dir = scratch / "old-dir"
	old_dir.mkdir()
	(old_dir / "f.txt").write_text("y", encoding="utf-8")
	_old(old_dir)
	new_file = scratch / "new.txt"
	new_file.write_text("z", encoding="utf-8")

	cfg = {"plugins": {"harness_scratch_purge": {"days_to_keep": 14, "paths": [str(scratch)]}}}
	res = asyncio.run(HarnessScratchPurgePlugin().execute(_janitor(), cfg))

	assert not old_file.exists()
	assert not old_dir.exists()
	assert new_file.exists()
	assert scratch.exists(), "nunca se borra el directorio configurado"
	assert res["harness_scratch_purged"] == 2


def test_harness_scratch_sin_paths_es_noop(tmp_path):
	cfg = {"plugins": {"harness_scratch_purge": {"days_to_keep": 14, "paths": []}}}
	res = asyncio.run(HarnessScratchPurgePlugin().execute(_janitor(), cfg))
	assert res["harness_scratch_purged"] == 0
