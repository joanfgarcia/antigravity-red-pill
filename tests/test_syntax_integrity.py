"""Syntax integrity: every Python source in the repo must compile.

Guardia del incidente del 24-jul: el Auto-Healer escribió líneas desindentadas
en distiller.py y el ciclo de sueño de las 03:00 murió con SyntaxError. Los
tests normales solo importan lo que usan, así que un archivo roto que nadie
importa pasa desapercibido — este test compila TODO el árbol, siempre.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_TREES = ("src", "scripts", "tools", "tests")


def test_all_python_sources_compile():
	failures = []
	for tree in SOURCE_TREES:
		base = ROOT / tree
		if not base.is_dir():
			continue
		for path in sorted(base.rglob("*.py")):
			if "__pycache__" in path.parts:
				continue
			try:
				compile(path.read_text(encoding="utf-8"), str(path), "exec")
			except SyntaxError as e:
				failures.append(f"{path.relative_to(ROOT)}:{e.lineno}: {e.msg}")

	assert not failures, "Broken Python sources found (¿Auto-Healer travieso?):\n" + "\n".join(failures)
