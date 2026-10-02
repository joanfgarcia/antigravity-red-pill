"""scripts/autonomy_ladder.py — jaula del arnés (sin modelo ni daemon)."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from red_pill.swarm.agents import local_minion

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "autonomy_ladder.py"


@pytest.fixture(scope="module")
def ladder():
	spec = importlib.util.spec_from_file_location("autonomy_ladder_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_jaula_del_arnes_reusa_la_politica_del_minion(ladder, monkeypatch, tmp_path):
	sandbox = tmp_path / "lab"
	(sandbox / "read").mkdir(parents=True)
	(sandbox / "read" / "manifest.txt").write_text("KEY3=vault-7731\n")
	monkeypatch.setattr(local_minion, "_dispatch", local_minion._dispatch)  # restaurado al terminar
	ladder.install_jail(sandbox)
	dispatch = local_minion._dispatch

	inside = json.loads(asyncio.run(dispatch("run_bash", {"command": "cat manifest.txt"}, str(sandbox / "read"))))
	assert "vault-7731" in inside["stdout"]
	# cwd fuera del sandbox: lo bloquea el arnés
	out = asyncio.run(dispatch("run_bash", {"command": "ls"}, str(tmp_path)))
	assert out.startswith(local_minion.JAIL_BLOCKED_PREFIX)
	# ruta que escapa del directorio de trabajo: lo bloquea la política del minion
	out = asyncio.run(dispatch("run_bash", {"command": "cat ../read/manifest.txt"}, str(sandbox / "read")))
	assert out.startswith(local_minion.JAIL_BLOCKED_PREFIX) and "vault" not in out
