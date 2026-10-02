"""Las recetas versionadas (`configs/jobs/`) no llevan rutas de un usuario concreto.

El repo es público y las recetas viajan con él: `cwd` ausente se ancla a la raíz
del repo (`load_recipe`), `manifest.workdir` relativo a ese `cwd`, y lo que vive
fuera del repo (venvs auxiliares) se alcanza con un `sh -c` explícito que expande
`$HOME` — el driver tokeniza con shlex y jamás expande `~` ni variables.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from red_pill.jobs.recipes import load_recipe

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = REPO_ROOT / "configs" / "jobs"


@pytest.mark.parametrize("recipe", sorted(RECIPES_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_receta_sin_rutas_de_usuario(recipe):
	text = recipe.read_text(encoding="utf-8")
	assert "/home/" not in text
	assert "/Users/" not in text


@pytest.mark.parametrize(
	"name",
	[
		"bakeoff_granite_42",
		"laya_adjudicate",
		"laya_router_bakeoff",
		"memento_redistill",
		"memento_redistill_full",
		"memento_reseed",
		"memento_redistill_fanout",
	],
)
def test_cwd_y_workdir_anclados_a_la_raiz_del_repo(name):
	_, payload, _, _, _ = load_recipe(str(RECIPES_DIR / f"{name}.yaml"))
	assert Path(payload["cwd"]) == REPO_ROOT
	manifest = payload.get("manifest") or {}
	if manifest:
		assert (Path(payload["cwd"]) / manifest["workdir"]).resolve() == REPO_ROOT


def _fake_python(path: Path) -> None:
	path.parent.mkdir(parents=True)
	path.write_text('#!/bin/sh\necho "PYTHONPATH=${PYTHONPATH:-} ARGS=$*"\n', encoding="utf-8")
	path.chmod(0o755)


@pytest.mark.parametrize(
	"name, venv_rel, expected",
	[
		("bakeoff_granite_42", ".local/share/red-pill/llmtools-venv", "PYTHONPATH=src ARGS=scripts/bakeoff_granite_42.py"),
		("laya_router_bakeoff", ".local/share/red-pill/laya-venv", "PYTHONPATH= ARGS=scripts/laya_router_bakeoff.py --n 120 --seed 7"),
	],
)
def test_venv_fuera_del_repo_se_resuelve_con_la_home_de_quien_ejecuta(tmp_path, name, venv_rel, expected):
	_, payload, _, _, _ = load_recipe(str(RECIPES_DIR / f"{name}.yaml"))
	command = payload["step_command"]
	assert isinstance(command, list) and command[:2] == ["sh", "-c"]

	home = tmp_path / "home"
	_fake_python(home / venv_rel / "bin" / "python")
	env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
	out = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30)
	assert out.stdout.strip() == expected


def test_laya_router_bakeoff_respeta_laya_venv(tmp_path):
	_, payload, _, _, _ = load_recipe(str(RECIPES_DIR / "laya_router_bakeoff.yaml"))
	venv = tmp_path / "otro-venv"
	_fake_python(venv / "bin" / "python")
	env = {"HOME": str(tmp_path / "sin-venv"), "LAYA_VENV": str(venv), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
	out = subprocess.run(payload["step_command"], cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30)
	assert "ARGS=scripts/laya_router_bakeoff.py" in out.stdout
