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
