#!/usr/bin/env python3
"""Guardarraíl de tamaño de documento — medible, no prosa.

Por qué existe
--------------
Los documentos se leen (por el Operador y por modelos pequeños locales) y se
cargan en contexto: un documento demasiado grande **no se asimila**, se hojea.
Poner "máximo 30 KB" en un README no lo cumple nadie; un script sí. Es la regla
del RFC-RECIPE-001 §2.5: *todos los topes viven en código, no en prosa*.

El criterio, y por qué son estos números
----------------------------------------
Los umbrales describen **la capacidad de asimilación de un modelo pequeño**
(7B-9B) en una sola lectura, medida en folios A4 técnicos:

    10 KB  ≈ 3-4 folios A4  ≈ 2,5-3 K tokens   → documento cómodo de una sentada
    30 KB  ≈  10 folios A4  ≈   7-8 K tokens   → ya es un capítulo, no un documento
    64 KB  ≈  21 folios A4  ≈  16-18 K tokens  → no se razona, se hojea

Referencia real (2026-10): `RFC_ALMA_Y_CORO` 27 KB → 9 páginas;
`agent_interop/README.md` 74 KB → 25 páginas.

⚠️ ESTO ES UNA HIPÓTESIS FECHADA, NO UNA LEY
--------------------------------------------
Los modelos avanzan y las técnicas también: lo que hoy ocupa un 9B, mañana lo
hace un 12B o un 27B en el mismo espacio, o el mismo 9B retiene el doble. Por eso
los números viven en las DOS constantes de abajo, con su fecha, y no dispersos:

- Si el objetivo pasa a modelos de 27B/30B, sube ambos umbrales (y actualiza la
  fecha de calibración).
- Si aparece una técnica de lectura por partes (RAG sobre el propio documento,
  chunking con índice), el umbral duro puede desaparecer y quedarse sólo el
  blando.
- **Nunca** cambies un número en mitad del código: son estas dos constantes o no
  es este criterio.

Uso
---
    python3 planner/tools/check_doc_size.py              # el desk (planner/)
    python3 planner/tools/check_doc_size.py --root ../sharing/docs
    python3 planner/tools/check_doc_size.py --strict     # falla también el blando

Salida: 0 si todo cabe; 1 si algo supera el umbral DURO (o el blando con
`--strict`). El aviso blando no rompe nada: es una señal de "ponle índice".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── CALIBRACIÓN (fecha: 2026-10-29, modelos objetivo: 7B-9B locales) ─────────
# Cambiar SOLO aquí, y anotar la fecha y el modelo objetivo del cambio.
#   10 KB ≈ 3-4 folios A4 técnicos → el documento se lee de una sentada.
#   30 KB ≈ 10 folios A4 técnicos → ya es un capítulo: divide en sub-carpeta.
SOFT_LIMIT_KB = 10.0
HARD_LIMIT_KB = 30.0

CALIBRATED_ON = "2026-10-29"
CALIBRATED_FOR = "modelos locales 7B-9B (asimilación en una sola lectura)"

# ── Exclusiones ─────────────────────────────────────────────────────────────
# Archivo histórico y bancos de memoria: crecen por diseño y no se leen enteros.
SKIP_DIR_PARTS = ("archive", "__pycache__", ".git", "node_modules")


def _human_pages(nbytes: int) -> float:
	"""Folios A4 técnicos estimados (~3.000 caracteres por página)."""
	try:
		chars = nbytes  # UTF-8 español: ~1 byte/carácter de media
		return round(chars / 3000.0, 1)
	except Exception:
		return 0.0


def _scan(root: Path):
	"""Devuelve [(ruta, KB)] de los .md bajo `root`, sin las exclusiones."""
	out = []
	for p in root.rglob("*.md"):
		if any(part in SKIP_DIR_PARTS for part in p.parts):
			continue
		try:
			size = p.stat().st_size
		except OSError:
			continue
		out.append((p, size / 1024.0))
	out.sort(key=lambda t: t[1], reverse=True)
	return out


def main() -> int:
	ap = argparse.ArgumentParser(description="Guardarraíl de tamaño de documento (medible, no prosa).")
	ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Raíz a medir (default: planner/).")
	ap.add_argument("--strict", action="store_true", help="Falla también si se supera el umbral blando.")
	args = ap.parse_args()

	root = Path(args.root).expanduser().resolve()
	if not root.is_dir():
		print(f"[doc-size] raíz inexistente: {root}", file=sys.stderr)
		return 2

	docs = _scan(root)
	soft = [(p, kb) for p, kb in docs if kb > SOFT_LIMIT_KB]
	hard = [(p, kb) for p, kb in docs if kb > HARD_LIMIT_KB]

	print(f"[doc-size] raíz: {root}")
	print(f"[doc-size] calibración: {CALIBRATED_ON} · {CALIBRATED_FOR}")
	print(f"[doc-size] umbrales: blando {SOFT_LIMIT_KB:g} KB (índice obligatorio) · duro {HARD_LIMIT_KB:g} KB (dividir)")
	print(f"[doc-size] documentos: {len(docs)} · > blando: {len(soft)} · > duro: {len(hard)}")

	if hard:
		print("\nSUPERAN EL UMBRAL DURO (30 KB → dividir en sub-carpeta + índice):")
		for p, kb in hard:
			print(f"  {kb:6.1f} KB  ~{_human_pages(kb * 1024):4.1f} pág  {p.relative_to(root)}")

	if soft:
		rest = [t for t in soft if t[1] <= HARD_LIMIT_KB]
		if rest:
			print("\nSUPERAN EL UMBRAL BLANDO (10 KB → deben llevar índice de secciones):")
			for p, kb in rest[:20]:
				print(f"  {kb:6.1f} KB  ~{_human_pages(kb * 1024):4.1f} pág  {p.relative_to(root)}")
			if len(rest) > 20:
				print(f"  … y {len(rest) - 20} más")

	if hard or (args.strict and soft):
		print("\n[doc-size] KO")
		return 1

	print("\n[doc-size] OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
