#!/usr/bin/env python3
"""Wrapper de compatibilidad: la herramienta vive en el paquete.

Forma canónica (cualquier Bünker, tras `bunker update`):

	red-pill tools dedup-archive [--execute] [--no-snapshot]

Se mantiene este entrypoint porque ya circula en notas y sesiones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from red_pill.tools.dedup_archive import main  # noqa: E402

if __name__ == "__main__":
	main()
