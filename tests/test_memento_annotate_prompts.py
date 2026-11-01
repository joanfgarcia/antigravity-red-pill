"""Versiones de prompt de `annotate` elegidas por el MODELO (2026-10-30).

La v2 nació alrededor de granite; con K2 como juez el 45% de las notas titulaban
"Joan me pide/cuenta…" (granite: 0%). El arreglo es una variante de prompt que
el perfil del modelo declara — no un `if` en el código.
"""

import pytest

from red_pill.memento.agentic import prompts, runtime


@pytest.fixture
def _limpia_env(monkeypatch):
	monkeypatch.delenv("MEMENTO_ANNOTATE_PROMPT", raising=False)
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", False)


def test_el_perfil_del_modelo_elige_la_variante(_limpia_env, monkeypatch):
	"""Sin override, la variante sale del perfil del juez.

	Se stubea la resolución porque el conftest hermético apunta a un BUNKER_HOME
	temporal sin `model_profiles.yaml`; lo que se prueba aquí es el CONTRATO
	(perfil → variante → huella), no el YAML del operador."""
	from red_pill.core import model_runtime as mr

	class _Resuelto:
		annotate_prompt_set = "v3"

	monkeypatch.setattr(mr, "resolve", lambda *_a, **_k: _Resuelto())
	assert runtime.annotate_prompt_set() == "v3"
	assert runtime.voice_v2_enabled() is True  # v3 reutiliza la voz v2


def test_override_explicito_gana_al_perfil(_limpia_env, monkeypatch):
	monkeypatch.setenv("MEMENTO_ANNOTATE_PROMPT", "v2")
	assert runtime.annotate_prompt_set() == "v2"
	monkeypatch.setenv("MEMENTO_ANNOTATE_PROMPT", "v1")
	assert runtime.annotate_prompt_set() == ""
	assert runtime.voice_v2_enabled() is False


def test_la_variante_entra_en_la_huella(_limpia_env, monkeypatch):
	from red_pill.core import model_runtime as mr

	class _Resuelto:
		annotate_prompt_set = "v3"

	monkeypatch.setattr(mr, "resolve", lambda *_a, **_k: _Resuelto())
	"""Cambiar de juez cambia `annotate_prompt_version` → las notas viejas dejan de
	contar como frescas y se re-anotan. Es el contrato de reanudación."""
	v3 = runtime.annotate_prompt_version()
	monkeypatch.setenv("MEMENTO_ANNOTATE_PROMPT", "v2")
	v2 = runtime.annotate_prompt_version()
	monkeypatch.setenv("MEMENTO_ANNOTATE_PROMPT", "v1")
	v1 = runtime.annotate_prompt_version()
	assert len({v3, v2, v1}) == 3


def test_v3_pide_el_acto_y_no_la_escena(_limpia_env):
	"""El contrato de v3 frente a v2: título = el hallazgo, y prohibición explícita
	de inventar la manera (era el defecto medido de K2)."""
	for v3, v2 in (
		(prompts.ANNOTATE_WORK_USER_V3, prompts.ANNOTATE_WORK_USER_V2),
		(prompts.ANNOTATE_SOCIAL_USER_V3, prompts.ANNOTATE_SOCIAL_USER_V2),
	):
		assert "TITLE — name the" in v3
		assert "Never open a title with" in v3
		assert "Do NOT invent how it was said" in v3 or "Do NOT invent the manner" in v3
		assert "TITLE — name the" not in v2
		assert "${fragment}" in v3  # sigue siendo una plantilla rendereable
