"""Tests del pre-pase determinista de estados del planner (AWAKEN-002 · A-4)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "planner_state_audit.py"


def _load():
	spec = importlib.util.spec_from_file_location("planner_state_audit_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _git_repo(tmp_path: Path, token: str) -> Path:
	repo = tmp_path / "repo"
	repo.mkdir()

	def g(*a):
		subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)

	g("init", "-q", "-b", "main")
	g("config", "user.email", "t@t")
	g("config", "user.name", "t")
	(repo / "f.txt").write_text("x", encoding="utf-8")
	g("add", ".")
	g("commit", "-q", "-m", f"feat: {token} implemented")
	return repo


def _desk_with_rfc(tmp_path: Path, rfc_id: str, status: str, extra: str = "") -> Path:
	desk = tmp_path / "desk"
	doc = desk / "planner" / "design" / "X" / "RFC_X.md"
	doc.parent.mkdir(parents=True)
	doc.write_text(f"---\nid: {rfc_id}\nstatus: {status}\n{extra}---\n\n# RFC\n", encoding="utf-8")
	return desk


def test_draft_con_evidencia_propone_in_progress(tmp_path):
	m = _load()
	repo = _git_repo(tmp_path, "AWAKEN-999")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "draft")
	results = m.audit(desk, [repo], max_commits=10)
	assert len(results) == 1
	kinds = {p["kind"] for p in results[0]["proposals"]}
	suggests = {p["suggest"] for p in results[0]["proposals"]}
	assert "stale-status" in kinds and "in-progress" in suggests


def test_blocked_sin_reason_es_bandera(tmp_path):
	m = _load()
	desk = _desk_with_rfc(tmp_path, "AWAKEN-111", "blocked")
	results = m.audit(desk, [], max_commits=10)
	assert any(p["kind"] == "missing-reason" for p in results[0]["proposals"])


def test_closed_sin_merge_es_bandera(tmp_path):
	m = _load()
	desk = _desk_with_rfc(tmp_path, "AWAKEN-222", "closed")
	results = m.audit(desk, [], max_commits=10)
	assert any(p["kind"] in {"unverified-closed", "no-evidence"} for p in results[0]["proposals"])


def test_only_filtra_por_id(tmp_path):
	m = _load()
	desk = tmp_path / "desk"
	for rid in ("AWAKEN-1", "AWAKEN-2"):
		doc = desk / "planner" / "design" / rid / "RFC.md"
		doc.parent.mkdir(parents=True)
		doc.write_text(f"---\nid: {rid}\nstatus: blocked\n---\n", encoding="utf-8")
	results = m.audit(desk, [], only="AWAKEN-2", max_commits=5)
	assert [r["id"] for r in results] == ["AWAKEN-2"]


def test_render_no_aplica_nada(tmp_path):
	m = _load()
	desk = _desk_with_rfc(tmp_path, "AWAKEN-333", "blocked")
	results = m.audit(desk, [], max_commits=5)
	md = m.render_markdown(results, desk, [])
	assert "Propuestas, no órdenes" in md
	assert (desk / "planner" / "design" / "X" / "RFC_X.md").read_text(encoding="utf-8").startswith("---\nid: AWAKEN-333\nstatus: blocked")


def test_repo_suma_al_del_cwd_y_no_duplica(tmp_path, monkeypatch):
	"""`--repo` AÑADE al repo del cwd: reemplazarlo perdía media evidencia."""
	m = _load()
	here = _git_repo(tmp_path, "AWAKEN-999")
	other = tmp_path / "other"
	other.mkdir()
	subprocess.run(["git", "-C", str(other), "init", "-q", "-b", "main"], check=True, capture_output=True, text=True)
	monkeypatch.chdir(here)

	repos = m._resolve_repos([str(other)])
	assert repos == [here.resolve(), other.resolve()]

	# Repetir el repo del cwd no lo duplica.
	assert m._resolve_repos([str(here), str(here)]) == [here.resolve()]

	# Fuera de un repo git, quedan solo los declarados.
	monkeypatch.chdir(tmp_path / "nowhere" if (tmp_path / "nowhere").mkdir() is None else tmp_path)
	assert m._resolve_repos([str(other)]) == [other.resolve()]


def test_token_candidates_baja_a_la_familia_pero_no_al_generico(tmp_path):
	"""Un commit cita `AWAKEN-002`, casi nunca `AWAKEN-002-DESIGN`."""
	m = _load()
	assert m._token_candidates("AWAKEN-002-DESIGN") == ["AWAKEN-002-DESIGN", "AWAKEN-002"]
	assert m._token_candidates("SPEC-B01-001") == ["SPEC-B01-001", "SPEC-B01", "B01-001"]
	# Sin dígito no se baja más: `SPEC`/`PLAN` arrastrarían medio repo.
	assert "SPEC" not in m._token_candidates("SPEC-B01-001")
	# El prefijo de familia se cae, el número se queda.
	assert m._token_candidates("PLAN-OBS-001") == ["PLAN-OBS-001", "OBS-001"]
	assert m._token_candidates("MEM-010-F7") == ["MEM-010-F7", "MEM-010"]


def test_evidencia_bajo_la_familia_no_se_lee_como_vacia(tmp_path):
	"""Trabajo real bajo la familia NO puede salir como `no-evidence` high."""
	m = _load()
	repo = _git_repo(tmp_path, "AWAKEN-999")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999-DESIGN", "in-progress")
	results = m.audit(desk, [repo], max_commits=10)
	assert len(results) == 1
	kinds = {p["kind"] for p in results[0]["proposals"]}
	assert "no-evidence" not in kinds
	assert "weak-evidence" in kinds
	assert results[0]["evidence"]["token_used"] == "AWAKEN-999"
	assert all(p["severity"] != "high" for p in results[0]["proposals"])


def test_sin_evidencia_ni_bajo_la_familia_sigue_siendo_high(tmp_path):
	"""La bajada a la familia no puede tapar la ausencia real de evidencia."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-1")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999-DESIGN", "implemented")
	results = m.audit(desk, [repo], max_commits=10)
	kinds = {p["kind"] for p in results[0]["proposals"]}
	assert "no-evidence" in kinds


def test_render_dice_bajo_que_token_hay_evidencia(tmp_path):
	m = _load()
	repo = _git_repo(tmp_path, "AWAKEN-999")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999-DESIGN", "in-progress")
	md = m.render_markdown(m.audit(desk, [repo], max_commits=10), desk, [repo])
	assert "token de evidencia: `AWAKEN-999`" in md
	# La cabecera no anuncia un "cambio" que no cambia nada.
	assert "`in-progress` → sin cambio (revisar a mano)" in md


def _head(repo: Path) -> str:
	out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
	return out.stdout.strip()


def test_evidencia_declarada_en_el_frontmatter_no_es_no_evidence(tmp_path):
	"""Un doc que nombra sus commits en `evidence:` no puede salir como vacío.

	El mensaje del commit no cita el id: la única ruta a esa evidencia es la
	declaración del propio documento. Antes salía `no-evidence` high.
	"""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-9")
	sha = _head(repo)
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "implemented", extra=f'evidence: ["{repo.name}:{sha}"]\n')
	assert m.audit(desk, [repo], max_commits=10) == []


def test_evidencia_declarada_que_no_existe_no_se_acepta(tmp_path):
	"""Declarar no es probar: un sha que no está en el repo no tapa la ausencia."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-9")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "implemented", extra=f'evidence: ["{repo.name}:deadbeef"]\n')
	kinds = {p["kind"] for p in m.audit(desk, [repo], max_commits=10)[0]["proposals"]}
	assert "no-evidence" in kinds


def test_evidencia_en_prosa_no_cuenta_como_evidencia(tmp_path):
	"""«R5 del 2026-10-14» no es direccionable: aceptarlo sería mentir al revés."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-9")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "implemented", extra="evidence: Remediación R5 del 2026-10-14 (rama feat/x)\n")
	kinds = {p["kind"] for p in m.audit(desk, [repo], max_commits=10)[0]["proposals"]}
	assert "no-evidence" in kinds


def test_evidencia_declarada_bajo_otro_nombre_de_repo_cuenta(tmp_path):
	"""Un worktree del mismo repo tiene otro nombre: el prefijo es pista, no candado."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-9")
	sha = _head(repo)
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "closed", extra=f'evidence: ["sharing:{sha}"]\n')
	# El prefijo se resuelve al repo real aunque se llame distinto.
	assert m._declared_evidence([repo], [f"sharing:{sha}"]) == [f"{repo.name}:{sha}"]
	# Y con la evidencia ya en una rama viva, `closed` queda verificado: nada que proponer.
	assert m.audit(desk, [repo], max_commits=10) == []


def _git_repo_named(parent: Path, name: str, token: str) -> Path:
	repo = parent / name
	repo.mkdir()

	def g(*a):
		subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)

	g("init", "-q", "-b", "main")
	g("config", "user.email", "t@t")
	g("config", "user.name", "t")
	(repo / "f.txt").write_text("x", encoding="utf-8")
	g("add", ".")
	g("commit", "-q", "-m", f"feat: {token} implemented")
	return repo


def test_proyecto_no_escaneado_no_se_vende_como_no_evidence(tmp_path):
	"""No haber mirado no es lo mismo que no existir: baja a `unscanned-project`."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-1")
	desk = _desk_with_rfc(tmp_path, "AWAKEN-999", "in-progress", extra="project: inexistente\n")
	results = m.audit(desk, [repo], max_commits=10)
	assert len(results) == 1
	props = results[0]["proposals"]
	assert {p["kind"] for p in props} == {"unscanned-project"}
	assert all(p["severity"] != "high" for p in props)
	assert "NO medido" in props[0]["reason"]


def test_repo_del_proyecto_se_descubre_junto_al_desk(tmp_path):
	"""El trabajo de un doc de `frankenswarm` está en su repo, no en el del cwd."""
	m = _load()
	_git_repo_named(tmp_path, "frankenswarm", "WSP-777")
	desk = _desk_with_rfc(tmp_path, "WSP-777", "in-progress", extra="project: frankenswarm\n")
	assert m.audit(desk, [], max_commits=10) == []


def test_alias_del_kernel_se_resuelve_al_repo_sharing(tmp_path):
	"""El proyecto `red-pill` vive en el repo `sharing`: sin alias no se mira."""
	m = _load()
	repo = _git_repo_named(tmp_path, "sharing", "SPEC-888")
	sha = _head(repo)
	desk = _desk_with_rfc(tmp_path, "SPEC-888", "implemented", extra=f'project: red-pill\nevidence: ["sharing:{sha}"]\n')
	assert m.audit(desk, [], max_commits=10) == []


def _commit_on(repo: Path, branch: str, token: str) -> str:
	def g(*a):
		subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)

	g("checkout", "-q", "-b", branch)
	(repo / f"{branch.replace(chr(47), chr(95))}.txt").write_text("y", encoding="utf-8")
	g("add", ".")
	g("commit", "-q", "-m", f"feat: {token} implemented")
	return _head(repo)


def test_closed_con_commit_en_la_rama_viva_no_pide_merge(tmp_path):
	"""El release squash-mergea: no hay commit de merge. `closed` con el trabajo
	en `next` (la rama viva de frankenswarm) está cerrado, no 'sin verificar'."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-1")
	sha = _commit_on(repo, "next", "WSP-555")
	desk = _desk_with_rfc(tmp_path, "WSP-555", "closed", extra=f'evidence: ["{repo.name}:{sha}"]\n')
	assert m.audit(desk, [repo], max_commits=10) == []


def test_closed_con_commit_fuera_de_la_rama_viva_sigue_bandera(tmp_path):
	"""En una rama de trabajo sin aterrizar, `closed` NO está verificado."""
	m = _load()
	repo = _git_repo(tmp_path, "OTRA-COSA-1")
	sha = _commit_on(repo, "feat/x", "WSP-666")
	desk = _desk_with_rfc(tmp_path, "WSP-666", "closed", extra=f'evidence: ["{repo.name}:{sha}"]\n')
	kinds = {p["kind"] for p in m.audit(desk, [repo], max_commits=10)[0]["proposals"]}
	assert "unverified-closed" in kinds
