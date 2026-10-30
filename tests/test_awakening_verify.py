"""El guardia del despertar degradado: sólo acusa a lo que puede demostrar falso.

Regresión del 2026-10-30: la primera versión marcaba como "inventada" la fecha
`20261029` y los ids de job caducados — también en el log de la propia agente.
Un guardia que grita en falso se ignora, así que esto queda fijado con tests.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.awakening_verify import verificar


@pytest.fixture
def repo(tmp_path):
	r = tmp_path / "repo"
	r.mkdir()
	subprocess.run(["git", "-C", str(r), "init", "-q"], check=True)
	subprocess.run(["git", "-C", str(r), "config", "user.email", "t@t"], check=True)
	subprocess.run(["git", "-C", str(r), "config", "user.name", "t"], check=True)
	(r / "a.txt").write_text("hola", encoding="utf-8")
	subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
	subprocess.run(["git", "-C", str(r), "commit", "-qm", "init"], check=True)
	return r


def _head(repo):
	return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_commit_real_pasa(repo):
	res = verificar(f"HEAD {_head(repo)[:7]} arreglado", repo=repo, jobs_dir=None)
	assert res["ok"] and res["n_fallidas"] == 0 and res["n_verificadas"] == 1


def test_commit_inventado_falla(repo):
	res = verificar("HEAD deadbeef arreglado", repo=repo, jobs_dir=None)
	assert not res["ok"] and res["fallidas"][0]["ancla"] == "deadbeef"


def test_fecha_no_es_un_ancla(repo):
	res = verificar("Despertar · 2026-10-30 · fichero 20261029_2000.log", repo=repo, jobs_dir=None)
	assert res["ok"] and res["n_fallidas"] == 0


def test_job_sin_estado_no_se_acusa(repo, tmp_path):
	res = verificar("el job e328f02f sigue FRUSTRATED", repo=repo, jobs_dir=tmp_path)
	assert res["ok"] and res["no_verificables"][0]["ancla"] == "e328f02f"


def test_job_con_estado_pasa(repo, tmp_path):
	(tmp_path / "e328f02f.log").write_text("x", encoding="utf-8")
	res = verificar("el job e328f02f sigue FRUSTRATED", repo=repo, jobs_dir=tmp_path)
	assert res["ok"] and res["n_verificadas"] == 1 and res["n_no_verificables"] == 0


def test_ruta_inexistente_falla(repo):
	res = verificar("leí /home/joan/no/existe/esto.md", repo=repo, jobs_dir=None)
	assert not res["ok"] and "no existe" in res["fallidas"][0]["motivo"]


def test_ruta_existente_pasa(repo):
	res = verificar(f"leí {repo / 'a.txt'}", repo=repo, jobs_dir=None)
	assert res["ok"]


def test_rama_inexistente_falla(repo):
	res = verificar("la rama `no-existe-esta` no tiene nada", repo=repo, jobs_dir=None)
	assert not res["ok"]


def test_rama_real_pasa(repo):
	subprocess.run(["git", "-C", str(repo), "branch", "next"], check=True)
	res = verificar("la rama `next` está limpia", repo=repo, jobs_dir=None)
	assert res["ok"]
