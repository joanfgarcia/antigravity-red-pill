"""Memento Chronicle (RFC-002): el archivo verbatim en disco, markdown y greppable.

La "grabadora" barata: cada sesión capturada vive como directorio
`<memento>/<AAAA-MM>/<source>/<session>/` con `memento/index.md` canónico.
Qdrant vuelve a ser memoria curada; esto es el archivo carpaccio del armario.

Módulos:
- `clean`: normalización de ruido compartida con el ingester (§5.2).
- `scrub`: scrubber de secretos MUST-9 — nada llega a disco sin pasar por él.
- `render`: mensajes normalizados → markdown canónico §4.2 (+ split views).
- `registry`: `memento_registry.json` + hilo prev/next por fuente (SHOULD 12).
"""

from __future__ import annotations

from pathlib import Path


def get_memento_root() -> Path:
	"""Raíz del árbol Memento: `MEMENTO_ROOT` si el operador la fija, si no `get_data_dir()/memento` (Q2)."""
	import red_pill.config as cfg
	from red_pill.core.paths import get_data_dir

	configured = str(getattr(cfg, "MEMENTO_ROOT", "") or "").strip()
	root = Path(configured).expanduser() if configured else get_data_dir() / "memento"
	root.mkdir(parents=True, exist_ok=True)
	return root
