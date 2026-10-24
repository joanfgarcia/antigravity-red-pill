"""Guardas del modelo de ramas (docs/CORE/WORKFLOWS.md §0, AD-054).

El flujo se siembra: regla de agente + templates del scaffold + selector `GIT_WORKFLOW`.
Estos tests fallan si el modelo documentado, la config y los artefactos sembrados divergen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from red_pill.config import RedPillConfig
from red_pill.core.git_workflow import GitWorkflowError, render_git_workflow

REPO = Path(__file__).resolve().parents[1]
SEED_RULE = REPO / "seeds" / "rules" / "git_workflow.md"
SCAFFOLD_RULE = REPO / "skills" / "scaffold-sovereign-project" / "templates" / "git_workflow.md"
SCAFFOLD_PREPUSH = REPO / "skills" / "scaffold-sovereign-project" / "templates" / "pre-push"
REPO_PREPUSH = REPO / "scripts" / "git-hooks" / "pre-push"
WORKFLOWS = REPO / "docs" / "CORE" / "WORKFLOWS.md"
CONVENTIONS = REPO / "docs" / "CORE" / "CONVENTIONS.md"


def test_git_workflow_default_y_validacion():
	assert RedPillConfig().GIT_WORKFLOW == "solo"
	assert RedPillConfig(GIT_WORKFLOW="canonical").GIT_WORKFLOW == "canonical"
	with pytest.raises(ValidationError):
		RedPillConfig(GIT_WORKFLOW="gitflow")


@pytest.mark.parametrize("path", [SEED_RULE, SCAFFOLD_RULE])
def test_regla_de_flujo_sembrada(path: Path):
	assert path.is_file(), f"falta la regla de flujo: {path}"
	text = path.read_text(encoding="utf-8")
	for needle in ("GIT_WORKFLOW", "canonical", "next", "squash", "profile:solo:start"):
		assert needle in text, f"{path.name}: falta '{needle}'"


@pytest.mark.parametrize("path", [SCAFFOLD_PREPUSH, REPO_PREPUSH])
def test_prepush_bloquea_main(path: Path):
	text = path.read_text(encoding="utf-8")
	assert "refs/heads/main" in text
	assert "REFUSED" not in text
	assert "exit 1" in text
	assert "GIT_WORKFLOW" in text
	assert "refs/heads/feat/" in text


def test_workflows_documenta_next_y_no_dev():
	text = WORKFLOWS.read_text(encoding="utf-8")
	assert "next" in text
	assert "git merge --squash" in text
	assert "`main` (stable), `dev` (integration)" not in text


def test_conventions_sin_dev_fantasma():
	assert "`dev` (integration)" not in CONVENTIONS.read_text(encoding="utf-8")


def test_render_seed_es_especifico_del_perfil():
	source = SEED_RULE.read_text(encoding="utf-8")
	solo = render_git_workflow("solo", source)
	canonical = render_git_workflow("canonical", source)
	assert "active profile: solo" in solo
	assert "active profile: canonical" in canonical
	assert "## `solo`" in solo and "## `canonical`" not in solo
	assert "## `canonical`" in canonical and "## `solo`" not in canonical
	assert "{{profile}}" not in solo + canonical
	assert "<!-- profile:" not in solo + canonical


def test_render_seed_rechaza_perfil_desconocido():
	with pytest.raises(GitWorkflowError):
		render_git_workflow("gitflow", SEED_RULE.read_text(encoding="utf-8"))
