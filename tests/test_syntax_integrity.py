"""Syntax integrity: every Python source in the whole repository must compile.

Guardia del incidente del 24-jul: el Auto-Healer escribió líneas desindentadas
en distiller.py y el ciclo de sueño de las 03:00 murió con SyntaxError. Los
tests normales solo importan lo que usan, así que un archivo roto que nadie
importa pasa desapercibido — este test compila TODO el .py del proyecto,
barriendo desde la raíz (una carpeta nueva queda cubierta por defecto).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Solo se excluye lo que NO es código nuestro: entornos, cachés y vendorizado.
EXCLUDED_PARTS = {
	".venv",
	".git",
	"__pycache__",
	".mypy_cache",
	".ruff_cache",
	".pytest_cache",
	"node_modules",
	"3rdparty",  # código externo vendorizado (BitNet) — no lo auditamos nosotros
}


def test_all_python_sources_compile():
	failures = []
	scanned = 0
	for path in sorted(ROOT.rglob("*.py")):
		if EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts):
			continue
		scanned += 1
		try:
			compile(path.read_text(encoding="utf-8"), str(path), "exec")
		except SyntaxError as e:
			failures.append(f"{path.relative_to(ROOT)}:{e.lineno}: {e.msg}")
		except UnicodeDecodeError as e:
			failures.append(f"{path.relative_to(ROOT)}: undecodable source ({e})")

	assert scanned > 100, f"Suspiciously few Python files scanned ({scanned}) — exclusion list too greedy?"
	assert not failures, "Broken Python sources found (¿Auto-Healer travieso?):\n" + "\n".join(failures)
