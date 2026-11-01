"""families.py — índice de familias de planner/design (generado).

Lo que se fija aquí: el recuento es literal (no un juicio), la fila avisa cuando a
una familia le falta puerta, y los documentos anidados cuentan.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
	"families", ROOT / "seeds" / "desk" / "planner" / "tools" / "families.py"
)
families = importlib.util.module_from_spec(spec)
spec.loader.exec_module(families)

FM = '---\ntitle: "x"\nstatus: {st}\nupdated: {up}\n---\n\ncuerpo\n'


def _doc(path: Path, status: str, updated: str = "2026-10-01") -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(FM.format(st=status, up=updated), encoding="utf-8")


def test_recuenta_estados_y_senala_familias_sin_puerta(tmp_path: Path) -> None:
	root = tmp_path / "design"
	_doc(root / "con_puerta" / "README.md", "in-progress", "2026-10-29")
	_doc(root / "con_puerta" / "B01.md", "implemented", "2026-10-20")
	_doc(root / "sin_puerta" / "UNICO.md", "draft")

	out = families.build(root)

	assert "**2 familias · 3 documentos** · **1 sin puerta**" in out
	assert "`in-progress` · `implemented`" in out, "el recuento es literal y ordenado"
	assert "2026-10-29" in out, "último cambio de la familia"
	assert "`sin_puerta/`" in out.split("Familias sin puerta")[1]
	assert "**falta**" in out


def test_cuenta_los_documentos_anidados(tmp_path: Path) -> None:
	root = tmp_path / "design"
	_doc(root / "fam" / "README.md", "active")
	_doc(root / "fam" / "sub" / "hondo.md", "implemented")

	out = families.build(root)
	assert "**1 familias · 2 documentos**" in out


def test_no_se_escribe_a_mano_se_marca_como_generado(tmp_path: Path) -> None:
	out = families.build(tmp_path)
	assert "NO editar a mano" in out
	assert 'author: "planner/tools/families.py (generado)"' in out
