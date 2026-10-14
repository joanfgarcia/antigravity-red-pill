"""`media-gen` — launcher de consola de generación de media, dirigido por el elenco.

`[project.scripts] media-gen = "red_pill.media_gen:main"` → `uv run media-gen …`
desde el repo. Delega en el launcher genérico (`scripts/imagegen/gen_cli.py`)
usando el **python del forge** (que trae torch/diffusers/sd.cpp), y hereda
stdout/exit code.

El launcher resuelve modelo/rol del elenco, hace snap al `dim_multiple`, libera la
VRAM del LLM residente y despacha por `backend` (diffusers / sd_cpp / bonsai). Con
`--image`/`--ref-image` edita o compone a partir de imágenes (backend sd_cpp).
"""

from __future__ import annotations

import os
import sys

from red_pill.core.paths import get_bunker_root, get_forge_home


def main() -> int:
	forge = get_forge_home("image")
	py = forge / "venv" / "bin" / "python"
	launcher = get_bunker_root() / "scripts" / "imagegen" / "gen_cli.py"
	if not py.is_file():
		print(f"[error] forge de imagen no encontrado en {py} (móntalo: scripts/imagegen/bootstrap.sh)", file=sys.stderr)
		return 1
	if not launcher.is_file():
		print(f"[error] launcher no encontrado: {launcher}", file=sys.stderr)
		return 1
	# exec: hereda stdin/stdout/stderr y el código de salida del launcher.
	os.execv(str(py), [str(py), str(launcher), *sys.argv[1:]])
	return 0  # inalcanzable (execv reemplaza el proceso)


if __name__ == "__main__":
	sys.exit(main())
