"""media_staging — staging de generación y promoción a destino definitivo (RFC-HARNESS-004 §8.2).

La generación media va a un **staging** temporal (no al desk ni a un destino
final); cuando el Operador/QA aprueba, `promote()` **mueve/copia el artefacto
elegido** al destino definitivo.

Staging configurable por env `RP_MEDIA_STAGING` (default `~/tmp/red-pill/media/staging`).
Subcarpeta por encargo: `<title>` descriptivo (elegido por el agente).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional

DEFAULT_STAGING = "~/tmp/red-pill/media/staging"
ARTIFACT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".flac", ".ogg", ".mp4"}


def staging_root() -> Path:
	"""Raíz del staging (env `RP_MEDIA_STAGING`, default `~/tmp/red-pill/media/staging`)."""
	return Path(os.path.expanduser(os.environ.get("RP_MEDIA_STAGING") or DEFAULT_STAGING))


def order_dir(title: str, create: bool = False) -> Path:
	"""Directorio de staging de un encargo (`<staging_root>/<title>`)."""
	path = staging_root() / title
	if create:
		path.mkdir(parents=True, exist_ok=True)
	return path


def list_artifacts(title: str) -> List[Path]:
	"""Artefactos media presentes en el staging de un encargo."""
	origin = order_dir(title)
	if not origin.is_dir():
		return []
	return sorted(p for p in origin.iterdir() if p.is_file() and p.suffix.lower() in ARTIFACT_SUFFIXES)


def promote(title: str, to: str, name: Optional[str] = None, move: bool = False) -> Path:
	"""Promociona un artefacto del staging `<title>` al destino definitivo `to`.

	- `name`: fichero concreto a promocionar (si se omite y hay varios → error, para no elegir a ciegas).
	- `move=True`: mueve (libera el staging); por defecto copia.
	Devuelve la ruta final.
	"""
	origin = order_dir(title)
	if not origin.is_dir():
		raise FileNotFoundError(f"staging no encontrado para '{title}': {origin}")

	artifacts = list_artifacts(title)
	if name:
		picked = origin / name
		if not picked.is_file():
			raise FileNotFoundError(f"artefacto '{name}' no existe en {origin}")
	elif len(artifacts) == 1:
		picked = artifacts[0]
	elif not artifacts:
		raise FileNotFoundError(f"sin artefactos media en {origin}")
	else:
		raise ValueError(
			f"hay {len(artifacts)} artefactos en {origin}; usa --name para elegir uno "
			f"({', '.join(a.name for a in artifacts)})"
		)

	dest_dir = Path(os.path.expanduser(to))
	dest_dir.mkdir(parents=True, exist_ok=True)
	dest = dest_dir / picked.name
	if move:
		shutil.move(str(picked), str(dest))
	else:
		shutil.copy2(picked, dest)
	return dest
