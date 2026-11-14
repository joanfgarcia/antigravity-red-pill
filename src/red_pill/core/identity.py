"""Ancla de identidad del puesto (MEM-006 P0): quién es el Operador y quién el agente.

Es la **única fuente de verdad** de nombre y género reales, y no la escribe un
LLM: la escribe el operador en su config. Los datos personales viven FUERA del
repo (`~/.config/red-pill/identity_bio.md`); el repo solo trae una plantilla
neutra, para que instalar red-pill no inyecte una identidad ajena.

Consumidores:
	- `red_pill.memento.agentic.prompts` — voz y género de las memorias.
	- `scripts/wake_up_v6.py` — bloque `OPERATOR_ANCHOR` del despertar.
	- `red_pill.metabolism.phases.operator_profile_phase` — ancla del prompt de
	síntesis del perfil (el perfil es *advisory*; el ancla manda).

Precedencia (idéntica desde MEM-006): `RP_IDENTITY_BIO` → config XDG →
plantilla neutra del paquete.
"""

from __future__ import annotations

import os
from pathlib import Path

# Plantilla neutra de respaldo. Sigue viviendo junto al pase Memento porque no
# es un prompt del pase: `tests/test_prompt_composition_ci.py` la excluye del
# check de huérfanos con `_EXCEPTIONS`. Si algún día el árbol de prompts se
# unifica, esta constante se muda con ella.
_NEUTRAL_TEMPLATE = (
	Path(__file__).resolve().parents[1] / "memento" / "agentic" / "prompts" / "identity_bio.template.txt"
)

# Último recurso: sin config y sin plantilla, al menos que quede la instrucción.
FALLBACK_ANCHOR = "IDENTIDAD: usa el nombre y el género reales del Operador y del agente."


def identity_bio_with_source() -> tuple[str, str]:
	"""Devuelve (bio, origen) con origen en {"override:<path>", "config", "template", "none"}."""
	override = os.getenv("RP_IDENTITY_BIO", "").strip()
	if override:
		try:
			text = Path(override).read_text(encoding="utf-8").strip()
			if text:
				return text, f"override:{override}"
		except OSError:
			pass

	from red_pill.core.paths import get_config_dir

	try:
		text = (Path(get_config_dir()) / "identity_bio.md").read_text(encoding="utf-8").strip()
		if text:
			return text, "config"
	except OSError:
		pass

	try:
		text = _NEUTRAL_TEMPLATE.read_text(encoding="utf-8").strip()
		if text:
			return text, "template"
	except OSError:
		pass

	return FALLBACK_ANCHOR, "none"


def load_identity_bio() -> str:
	"""Bio de identidad resuelta (sin metadatos de origen)."""
	return identity_bio_with_source()[0]


def operator_anchor() -> str:
	"""Bloque inyectable en el contexto de despertar, o "" si solo hay plantilla neutra.

	Devolver "" con plantilla neutra es deliberado: una plantilla genérica no
	ancla nada y ocupar sitio en el contexto solo añade ruido.
	"""
	text, source = identity_bio_with_source()
	return "" if source == "template" else text
