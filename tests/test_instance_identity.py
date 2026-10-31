"""Sandbox de identidad de instancia (P1-ARNES-003).

El repo es motor genérico + novela: la identidad activa (nombre del agente y del
Operador) es configuración del puesto, no del repo. Corre en el sandbox de
`conftest` (Qdrant `:memory:`, XDG y AGENT_CORE_DIR redirigidos).

Medida de calidad acordada con el Operador (2026-10-18): **equivalencia** — al
resolver los placeholders con los nombres del puesto, el texto debe ser idéntico
al que había antes (byte a byte). Los nombres de los tests son datos de prueba
(no identidad real); las heurísticas de calidad no se tocan.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PKG = _REPO / "src" / "red_pill"
_AGENT, _OPERATOR = "Aleth", "Joan"  # nombres del puesto (datos de test)

# Ficheros convertidos a placeholders (deben reproducir el original al resolver).
_CONVERTED_FILES = [
	"src/red_pill/metabolism/prompts/distiller_v3_voice.txt",
	"src/red_pill/metabolism/prompts/engram_quality_auditor.txt",
	"src/red_pill/memento/agentic/prompts/annotate_work_user.txt",
	"src/red_pill/memento/agentic/prompts/annotate_work_user_v2.txt",
	"src/red_pill/memento/agentic/prompts/annotate_work_system.txt",
	"src/red_pill/memento/agentic/prompts/annotate_social_user.txt",
	"src/red_pill/memento/agentic/prompts/annotate_social_user_v2.txt",
	"src/red_pill/memento/agentic/prompts/annotate_social_system.txt",
	"src/red_pill/memento/agentic/prompts/voice_rewrite_user.txt",
	"src/red_pill/memento/agentic/prompts/voice_rewrite_user_v2.txt",
	"src/red_pill/memento/agentic/prompts/voice_rewrite_system.txt",
	"src/red_pill/memento/agentic/prompts/content_validate_user.txt",
	"src/red_pill/memento/agentic/prompts/content_validate_system.txt",
	"src/red_pill/memento/agentic/prompts/dual_score_user.txt",
	"src/red_pill/memento/agentic/prompts/dual_score_user_v2.txt",
	"src/red_pill/memento/agentic/prompts/refine_social_user.txt",
	"src/red_pill/memento/agentic/prompts/refine_multi_user.txt",
	"src/red_pill/prompts/fragments/voice.txt",
	"src/red_pill/prompts/fragments/voice_annotate.txt",
	"src/red_pill/cognitive/prompts/drive_evaluator_user.txt",
	"src/red_pill/inference/prompts/samantha_compact_user.txt",
]
_METABOLISM_PROMPTS = {
	"metabolism/prompts/distiller_v3_voice.txt": "distiller_v3_voice",
	"metabolism/prompts/engram_quality_auditor.txt": "engram_quality_auditor",
}
_LITERAL = ("Aleth", "Aletheia", "Joan")


def _es_subsecuencia(original: list[str], actual: list[str]) -> bool:
	"""¿Todas las líneas del original siguen en `actual`, en el mismo orden?"""
	i = 0
	for linea in actual:
		if i < len(original) and linea == original[i]:
			i += 1
	return i == len(original)


def _resolve(text: str) -> str:
	return text.replace("${agent_name}", _AGENT).replace("${operator_name}", _OPERATOR)


# Baseline congelada por fichero (2026-10-30). La medida del Operador es sobre la
# CONVERSIÓN a placeholders, no sobre el contenido para siempre: si un prompt se
# edita a propósito después, comparar contra `main` da rojo legítimo y obliga a
# tocar el test. Para esos ficheros se congela el original PRE-placeholders en
# `tests/fixtures/identity_baseline/<nombre>`. Congelar aquí es una decisión
# consciente: los prompts de identidad no se editan sin querer.
_BASELINE_FIXTURE = {
	"src/red_pill/metabolism/prompts/distiller_v3_voice.txt": "distiller_v3_voice.txt",
}


def _git_original(rel_path: str) -> str:
	fixture = _BASELINE_FIXTURE.get(rel_path)
	if fixture:
		base = _REPO / "tests" / "fixtures" / "identity_baseline" / fixture
		if not base.exists():
			pytest.skip(f"baseline congelada ausente para {rel_path}")
		return base.read_text(encoding="utf-8")
	out = subprocess.run(["git", "-C", str(_REPO), "show", f"main:{rel_path}"], capture_output=True, text=True)
	if out.returncode != 0:
		pytest.skip(f"git/main no disponible para {rel_path}")
	return out.stdout


def test_siembra_no_inyecta_identidad_de_instancia():
	"""Siembra real en el sandbox: ningún engrama de directiva nombra la instancia."""
	from red_pill.memory import MemoryManager
	from red_pill.seed import seed_project

	manager = MemoryManager()
	seed_project(manager)
	points, _ = manager.client.scroll(collection_name="directive_memories", limit=500, with_payload=True)
	blob = "\n".join(str((p.payload or {}).get("content", "")) for p in points)
	assert not any(lit in blob for lit in _LITERAL), f"engramas sembrados con identidad: {_LITERAL}"


def test_ficheros_convertidos_sin_literales():
	"""Los ficheros convertidos no llevan nombres literales: van por placeholder."""
	offenders = [rel for rel in _CONVERTED_FILES if any(lit in (_REPO / rel).read_text(encoding="utf-8") for lit in _LITERAL)]
	assert not offenders, "con literales: " + ", ".join(offenders)


def test_equivalencia_byte_a_byte():
	"""Medida del Operador: resolver los placeholders con los nombres del puesto
	reproduce EXACTAMENTE el texto original (antes de poner placeholders)."""
	mismatched = []
	for rel in _CONVERTED_FILES:
		new = _resolve((_REPO / rel).read_text(encoding="utf-8"))
		old = _resolve(_git_original(rel))
		if rel in _BASELINE_FIXTURE:
			# Fichero editado a propósito tras la conversión: la garantía ya no es
			# igualdad, es NO PÉRDIDA — cada línea del original debe seguir ahí, en
			# orden. Añadir reglas está permitido (y se ve); quitar o torcer una
			# línea que venía de la conversión, no.
			if not _es_subsecuencia(old.splitlines(), new.splitlines()):
				mismatched.append(f"{rel} (se perdió o cambió alguna línea del original)")
		elif new != old:
			mismatched.append(rel)
	assert not mismatched, "la sustitución no reproduce el original en: " + ", ".join(mismatched)


def test_render_metabolism_sin_placeholders_pendientes():
	"""Render con instancia genérica: no quedan `${...}` sin resolver."""
	from red_pill.core import prompts as core

	static = {"agent_name": "Agente", "operator_name": "Operador", "prompt_language": "es"}
	for rel, pid in _METABOLISM_PROMPTS.items():
		if not core.is_declared("metabolism", pid):
			continue
		text = core.resolve("metabolism", pid, static=static).text
		assert "${" not in text.replace("$$", ""), f"{pid}: placeholder sin resolver"
