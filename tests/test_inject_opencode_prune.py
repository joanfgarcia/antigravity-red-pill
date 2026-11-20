"""Reseed convergente de plugins de opencode: lo viejo no se queda al lado de lo nuevo.

Dos plugins de identidad conviviendo inyectan dos veces por turno, y uno de los
dos lo hace con el criterio viejo. El reseed tiene que retirar lo que ya no está
en la semilla, no solo escribir lo nuevo encima.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from inject.opencode.inject import _prune_stale_plugins  # noqa: E402


def _preparar(tmp_path: Path, seed: list[str], desplegados: list[str]) -> tuple[Path, Path]:
	seed_dir = tmp_path / "seed"
	dest_dir = tmp_path / "dest"
	seed_dir.mkdir()
	dest_dir.mkdir()
	for f in seed:
		(seed_dir / f).write_text("// seed", encoding="utf-8")
	for f in desplegados:
		(dest_dir / f).write_text("// desplegado", encoding="utf-8")
	return seed_dir, dest_dir


def test_retira_el_plugin_viejo_y_deja_bak(tmp_path):
	seed, dest = _preparar(tmp_path, ["redpill-harness.js"], ["redpill-harness.js", "redpill-wake.js"])
	retirados = _prune_stale_plugins(str(dest), str(seed), backup=True)
	assert retirados == 1
	assert not (dest / "redpill-wake.js").exists()
	assert (dest / "redpill-wake.js.bak").exists(), "lo retirado se conserva para volver atrás"
	assert (dest / "redpill-harness.js").exists()


def test_no_toca_plugins_ajenos(tmp_path):
	seed, dest = _preparar(tmp_path, ["redpill-harness.js"], ["redpill-harness.js", "cheaper-inference-catalog.js"])
	assert _prune_stale_plugins(str(dest), str(seed), backup=True) == 0
	assert (dest / "cheaper-inference-catalog.js").exists(), "un plugin que no es nuestro no se toca"


def test_es_idempotente(tmp_path):
	seed, dest = _preparar(tmp_path, ["redpill-harness.js"], ["redpill-harness.js", "redpill-old.js"])
	assert _prune_stale_plugins(str(dest), str(seed), backup=False) == 1
	assert _prune_stale_plugins(str(dest), str(seed), backup=False) == 0
