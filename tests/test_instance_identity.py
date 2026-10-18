"""Sandbox de identidad de instancia (P1-ARNES-003).

El repo es motor genérico + novela: la identidad activa (nombre del agente y del
Operador) es configuración del puesto, no del repo. Este test corre en el sandbox
de `conftest` (Qdrant `:memory:`, XDG y AGENT_CORE_DIR redirigidos).

Alcance acordado con el Operador (2026-10-18):
- **Siembra**: los engramas sembrados no nombran ninguna instancia.
- **Prompts con sustitución** (`metabolism`): usan `${agent_name}`/`${operator_name}`
  y al resolverlos con los nombres del puesto reproducen **byte a byte** el texto
  original (medida de calidad: la plantilla no cambia el resultado).
- Los prompts de `memento`/`cognitive`/`inference` conservan nombres propios como
  **texto conocido/ejemplos** hasta que el motor sustituya también los *system
  prompts*. No son fuga de identidad inyectada.
- Las heurísticas de calidad (`annotation_quality`, `embed_text`): sus nombres son
  datos reales de test; NO se tocan.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_INSTANCE = re.compile(r"\b(Aleth|Aletheia|Joan)\b")
_REPO = Path(__file__).resolve().parents[1]
_PKG = _REPO / "src" / "red_pill"

# Prompts que YA usan el motor de sustitución (metabolism) → equivalencia exigible.
_CONVERTED = {
	"metabolism/prompts/distiller_v3_voice.txt": "distiller_v3_voice",
	"metabolism/prompts/engram_quality_auditor.txt": "engram_quality_auditor",
}
_AGENT, _OPERATOR = "Aleth", "Joan"  # nombres reales del puesto (para equivalencia)


def _resolve_placeholders(text: str) -> str:
	return text.replace("${agent_name}", _AGENT).replace("${operator_name}", _OPERATOR)


def _git_original(rel_path: str) -> str:
	out = subprocess.run(
		["git", "-C", str(_REPO), "show", f"main:{rel_path}"],
		capture_output=True,
		text=True,
	)
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
	assert not _INSTANCE.search(blob), f"engramas sembrados con identidad de instancia: {_INSTANCE.findall(blob)}"


def test_prompts_convertidos_usan_placeholders():
	"""Los prompts ya convertidos no llevan nombres literales: van por placeholder."""
	offenders = [rel for rel in _CONVERTED if _INSTANCE.search((_PKG / rel).read_text(encoding="utf-8"))]
	assert not offenders, "prompts convertidos con nombres literales: " + ", ".join(offenders)


def test_equivalencia_de_plantillas_convertidas():
	"""Calidad (medida del Operador): resolver los placeholders con los nombres del
	puesto reproduce EXACTAMENTE el texto original (antes de poner placeholders)."""
	mismatched = []
	for rel in _CONVERTED:
		new = _resolve_placeholders((_PKG / rel).read_text(encoding="utf-8"))
		old = _resolve_placeholders(_git_original(f"src/red_pill/{rel}"))
		if new != old:
			mismatched.append(rel)
	assert not mismatched, "la sustitución no reproduce el original en: " + ", ".join(mismatched)


def test_render_convertidos_sin_placeholders_pendientes():
	"""Render con instancia genérica: no quedan `${...}` sin resolver."""
	from red_pill.core import prompts as core

	static = {"agent_name": "Agente", "operator_name": "Operador", "prompt_language": "es"}
	for rel, pid in _CONVERTED.items():
		if not core.is_declared("metabolism", pid):
			continue
		text = core.resolve("metabolism", pid, static=static).text
		assert "${" not in text.replace("$$", ""), f"{pid}: placeholder sin resolver"
