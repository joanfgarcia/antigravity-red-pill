"""Tests de la auditoría determinista de ramas pendientes de aterrizar."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "branch_landing_audit.py"


def _load():
	spec = importlib.util.spec_from_file_location("branch_landing_audit_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = mod
	spec.loader.exec_module(mod)
	return mod


def _repo(tmp_path: Path) -> Path:
	repo = tmp_path / "repo"
	repo.mkdir()
	_g(repo, "init", "-q", "-b", "main")
	_g(repo, "config", "user.email", "t@t")
	_g(repo, "config", "user.name", "t")
	(repo / "base.txt").write_text("base\n", encoding="utf-8")
	_g(repo, "add", ".")
	_g(repo, "commit", "-q", "-m", "chore: base")
	return repo


def _g(repo: Path, *args: str) -> None:
	subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _branch_with(repo: Path, name: str, files: dict[str, str | None]) -> None:
	"""Crea una rama desde main con ficheros (None = borrar)."""
	_g(repo, "checkout", "-q", "-b", name, "main")
	for rel, content in files.items():
		path = repo / rel
		if content is None:
			_g(repo, "rm", "-q", rel)
			continue
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(content, encoding="utf-8")
		_g(repo, "add", rel)
	_g(repo, "commit", "-q", "-m", f"feat: {name}")
	_g(repo, "checkout", "-q", "main")


def _status(mod, repo: Path, branch: str) -> str:
	verdicts = mod.audit(repo, "main", ("awaken/*", "parked/*"))
	return next(v.status for v in verdicts if v.branch == branch)


def test_merged_branch_is_reported_merged(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/real-merge", {"a.txt": "a\n"})
	_g(repo, "merge", "-q", "--no-ff", "-m", "merge", "awaken/real-merge")
	assert _status(mod, repo, "awaken/real-merge") == "merged"


def test_squash_merged_branch_has_no_content_to_land(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/squashed", {"b.txt": "b\n"})
	# El release squash-mergea: un commit nuevo con el mismo contenido, SHA distinto.
	(repo / "b.txt").write_text("b\n", encoding="utf-8")
	_g(repo, "add", "b.txt")
	_g(repo, "commit", "-q", "-m", "next → main: release")
	assert mod._is_ancestor(repo, "awaken/squashed", "main") is False
	assert _status(mod, repo, "awaken/squashed") == "same_content"


def test_divergent_branch_is_pending_and_green(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/pending", {"c.txt": "c\n", "d.txt": "d\n"})
	assert _status(mod, repo, "awaken/pending") == "clean"
	verdict = mod.audit(repo, "main", ("awaken/*",))[0]
	assert verdict.ahead == 1
	assert verdict.files_touched == 2
	assert sorted(verdict.files_differing) == ["c.txt", "d.txt"]
	assert verdict.conflict_files == []


def test_conflicting_branch_lists_conflict_files(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/conflicting", {"base.txt": "rama\n"})
	(repo / "base.txt").write_text("main\n", encoding="utf-8")
	_g(repo, "add", "base.txt")
	_g(repo, "commit", "-q", "-m", "fix: main cambia la misma línea")
	verdict = next(v for v in mod.audit(repo, "main", ("awaken/*",)) if v.branch == "awaken/conflicting")
	assert verdict.status == "conflict"
	assert verdict.conflict_files == ["base.txt"]


def test_branch_touching_nothing_is_no_changes(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_g(repo, "checkout", "-q", "-b", "awaken/empty")
	_g(repo, "commit", "-q", "--allow-empty", "-m", "chore: nada")
	_g(repo, "checkout", "-q", "main")
	assert _status(mod, repo, "awaken/empty") == "no_changes"


def test_patterns_filter_branches(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/x", {"x.txt": "x\n"})
	_branch_with(repo, "feature/y", {"y.txt": "y\n"})
	names = [v.branch for v in mod.audit(repo, "main", ("awaken/*",))]
	assert names == ["awaken/x"]


def test_missing_target_raises(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	try:
		mod.audit(repo, "next", ("awaken/*",))
	except mod.GitError:
		return
	raise AssertionError("un destino inexistente debe fallar, no inventarse un estado")


def test_render_marks_same_content_as_not_landable(tmp_path: Path) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/squashed", {"b.txt": "b\n"})
	(repo / "b.txt").write_text("b\n", encoding="utf-8")
	_g(repo, "add", "b.txt")
	_g(repo, "commit", "-q", "-m", "release")
	text = mod.render(mod.audit(repo, "main", ("awaken/*",)), repo, "main")
	assert "same_content" in text
	assert "Ninguna rama con contenido pendiente" in text


def test_additions_present_aunque_el_fichero_crezca(tmp_path: Path) -> None:
	"""El caso real: squash-merge y el fichero (CHANGELOG) sigue creciendo.

	La comparación por fichero completo lo daba por pendiente para siempre; sus
	adiciones, en cambio, ya están en el destino.
	"""
	mod = _load()
	repo = _repo(tmp_path)
	(repo / "doc.md").write_text("## Unreleased\n\nviejo\n", encoding="utf-8")
	_g(repo, "add", "doc.md")
	_g(repo, "commit", "-q", "-m", "docs: base")
	_branch_with(repo, "awaken/doc", {"doc.md": "## Unreleased\n\n### Nuevo\n\n- bloque\n\nviejo\n"})
	# El destino ya tiene el bloque y ENCIMA una sección posterior.
	(repo / "doc.md").write_text("## Unreleased\n\n### Nuevo\n\n- bloque\n\n### Otro\n\n- extra\n\nviejo\n", encoding="utf-8")
	_g(repo, "add", "doc.md")
	_g(repo, "commit", "-q", "-m", "docs: otra sección después")
	verdict = next(v for v in mod.audit(repo, "main", ("awaken/*",)) if v.branch == "awaken/doc")
	assert verdict.status == "same_content"
	assert verdict.evidence == "additions_present"


def test_rama_con_borrados_no_se_da_por_aterrizada(tmp_path: Path) -> None:
	"""Si la rama borra o reescribe, no se adivina: pendiente."""
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "awaken/rewrite", {"base.txt": "rama\n"})
	(repo / "base.txt").write_text("rama\nmain-extra\n", encoding="utf-8")
	_g(repo, "add", "base.txt")
	_g(repo, "commit", "-q", "-m", "fix: main reescribe y añade")
	verdict = next(v for v in mod.audit(repo, "main", ("awaken/*",)) if v.branch == "awaken/rewrite")
	assert verdict.status != "same_content"


def test_parked_no_cuenta_para_strict_salvo_include_parked(tmp_path: Path, monkeypatch, capsys) -> None:
	mod = _load()
	repo = _repo(tmp_path)
	_branch_with(repo, "parked/aparcada", {"p.txt": "p\n"})
	monkeypatch.chdir(repo)

	monkeypatch.setattr(sys, "argv", ["branch_landing_audit.py", "--strict"])
	assert mod.main() == 0
	assert "por diseño" in capsys.readouterr().out

	monkeypatch.setattr(sys, "argv", ["branch_landing_audit.py", "--strict", "--include-parked"])
	assert mod.main() == 1
