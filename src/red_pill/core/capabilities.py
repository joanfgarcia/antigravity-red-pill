"""capabilities — capacidades media activas en ESTA máquina (docs/TECHNICAL/DECISION_LOG.md).

Una familia (image_gen/audio_gen/music_gen) está **activa** si su harness está
**configurado en esta máquina**: el venv del forge existe y (para imagen/audio) hay
caché de pesos. **No** depende del elenco `media_profiles.yaml` (que puede no estar
sembrado). Gatea la **siembra de skills** (`capability:` en su frontmatter) y, a
futuro, la inyección en el handshake. Cero torch/subprocess/escaneo pesado.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from red_pill.core.paths import get_forge_home

_FAMILIES = ("image_gen", "audio_gen", "music_gen")
_HF_CACHE_REQUIRED = {"image_gen", "audio_gen"}  # música es tool-chain (sin pesos)


def active_families() -> List[str]:
	"""Familias media configuradas en esta máquina (harness presente).

	Señal por-máquina: venv del forge (+ caché de pesos para imagen/audio). Un
	equipo sin el harness instalado no activa la familia → sus skills no se siembran.
	"""
	active: List[str] = []
	for family in _FAMILIES:
		home = get_forge_home(family.split("_")[0])
		if not (home / "venv").exists():
			continue
		if family in _HF_CACHE_REQUIRED and not (home / "hf-cache").exists():
			continue
		active.append(family)
	return active


def enabled_for(capability: Optional[str]) -> bool:
	"""¿Se debe sembrar una skill que declara `capability: <x>`?

	`None`/vacío → siempre. `media` → cualquier familia media activa. Si no, la
	familia concreta debe estar activa.
	"""
	if not capability:
		return True
	active = set(active_families())
	if capability == "media":
		return bool(active)
	return capability in active


def _read_capability(skill_md: Path) -> Optional[str]:
	"""Lee `capability:` del frontmatter YAML de un SKILL.md (sin dependencias)."""
	try:
		lines = skill_md.read_text(encoding="utf-8").splitlines()
	except OSError:
		return None
	if not lines or lines[0].strip() != "---":
		return None
	for line in lines[1:]:
		if line.strip() == "---":
			break
		if line.startswith("capability:"):
			return line.split(":", 1)[1].strip() or None
	return None


def skill_enabled(skill_md: Path) -> bool:
	"""Decide si un SKILL.md debe sembrarse, según su `capability:`."""
	return enabled_for(_read_capability(skill_md))
