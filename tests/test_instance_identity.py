"""Sandbox de identidad de instancia (P1-ARNES-003).

El repo NO puede contener identidad de instancia ("Aleth"/"Joan"): es motor
genérico + novela. Este test corre en el sandbox de `conftest` (Qdrant `:memory:`,
XDG y AGENT_CORE_DIR redirigidos) y comprueba, sobre una SIEMBRA real:

1. Los engramas sembrados no nombran una instancia.
2. Los prompts del repo no hardcodean nombres de instancia.
3. Al renderizar con una instancia genérica, no aparece ningún nombre fijo.
"""

from __future__ import annotations

import re
from pathlib import Path

# Nombres de la instancia del Operador — NUNCA en el repo.
_INSTANCE = re.compile(r"\b(Aleth|Aletheia|Joan)\b")
_PKG = Path(__file__).resolve().parents[1] / "src" / "red_pill"


def _prompt_files() -> list[Path]:
	files: list[Path] = []
	for pat in ("prompts/*.txt", "prompts/**/*.txt", "prompts/**/*.yaml", "prompts/**/*.yml"):
		files += list(_PKG.rglob(pat))
	# excluir la bio real si algún día se copiara dentro del paquete
	return [f for f in set(files) if f.name != "identity_bio.md"]


def test_siembra_no_inyecta_identidad_de_instancia():
	"""Siembra real en el sandbox: ningún engrama de directiva nombra la instancia."""
	from red_pill.memory import MemoryManager
	from red_pill.seed import seed_project

	manager = MemoryManager()
	seed_project(manager)
	points, _ = manager.client.scroll(collection_name="directive_memories", limit=500, with_payload=True)
	blob = "\n".join(str((p.payload or {}).get("content", "")) for p in points)
	assert not _INSTANCE.search(blob), f"engramas sembrados con identidad de instancia: {_INSTANCE.findall(blob)}"


def test_prompts_sin_nombres_de_instancia():
	"""Los prompts del paquete no hardcodean 'Aleth'/'Joan' (van por identidad)."""
	offenders = sorted(str(p.relative_to(_PKG)) for p in _prompt_files() if _INSTANCE.search(p.read_text(encoding="utf-8")))
	assert not offenders, "prompts con identidad de instancia: " + ", ".join(offenders)


def test_render_con_instancia_generica_no_filtra_nombres():
	"""Renderizado con instancia genérica: los prompts de metabolism quedan limpios."""
	from red_pill.core import prompts as core

	static = {"agent_name": "Agente", "operator_name": "Operador", "prompt_language": "es"}
	for pid in ("distiller_v3", "distiller_v3_voice", "engram_quality_auditor"):
		if not core.is_declared("metabolism", pid):
			continue
		text = core.resolve("metabolism", pid, static=static).text
		assert not _INSTANCE.search(text), f"{pid} filtra identidad: {_INSTANCE.findall(text)}"
