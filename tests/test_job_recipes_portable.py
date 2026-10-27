"""Las recetas versionadas (`configs/jobs/`) no llevan rutas de un usuario concreto.

El repo es público y las recetas viajan con él. Se ejecutan **post-siembra**, así que
resuelven por **env** (sembrado por el runner, `queue_worker._load_job_env`): `$IA_DIR`
(raíz del repo), `$<VENV>_VENV` (venvs auxiliares fuera del repo), `$RP_MEDIA_STAGING`…
`cwd` ausente se ancla a la raíz del repo (`load_recipe`). Nada de `/home/`, `~/` ni
`$HOME`-based: el driver tokeniza con shlex y no expande `~`/variables.
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
		"cloud_backup",
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
	"name, venv_var, script, args",
	[
		("bakeoff_granite_42", "LLMTOOLS_VENV", "bakeoff_granite_42.py", ""),
		("laya_router_bakeoff", "LAYA_VENV", "laya_router_bakeoff.py", " --n 120 --seed 7"),
	],
)
def test_venv_fuera_del_repo_se_resuelve_por_env(tmp_path, name, venv_var, script, args):
	"""Post-siembra: el venv (fuera del repo) y el script (repo) resuelven por ENV."""
	_, payload, _, _, _ = load_recipe(str(RECIPES_DIR / f"{name}.yaml"))
	command = payload["step_command"]
	assert isinstance(command, list) and command[:2] == ["sh", "-c"]

	venv = tmp_path / "venv"
	_fake_python(venv / "bin" / "python")
	env = {venv_var: str(venv), "IA_DIR": str(REPO_ROOT), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
	out = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30)
	assert out.stdout.strip().endswith(f"ARGS={REPO_ROOT}/scripts/{script}{args}")


def test_laya_router_bakeoff_usa_laya_venv_del_env(tmp_path):
	"""`$LAYA_VENV` (sembrado por el runner) manda; script absoluto vía `$IA_DIR`."""
	_, payload, _, _, _ = load_recipe(str(RECIPES_DIR / "laya_router_bakeoff.yaml"))
	venv = tmp_path / "otro-venv"
	_fake_python(venv / "bin" / "python")
	env = {"LAYA_VENV": str(venv), "IA_DIR": str(REPO_ROOT), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
	out = subprocess.run(payload["step_command"], cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30)
	assert f"ARGS={REPO_ROOT}/scripts/laya_router_bakeoff.py" in out.stdout
