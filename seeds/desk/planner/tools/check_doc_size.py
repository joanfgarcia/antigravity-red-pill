#!/usr/bin/env python3
"""Guardarraíl de tamaño de documento — medible, no prosa.

Por qué existe
--------------
Los documentos se leen (por el Operador y por modelos pequeños locales) y se
cargan en contexto: un documento demasiado grande **no se asimila**, se hojea.
Poner "máximo 30 KB" en un README no lo cumple nadie; un script sí. Es la regla
del RFC-RECIPE-001 §2.5: *todos los topes viven en código, no en prosa*.

La unidad es TOKENS, no KB
--------------------------
El KB es lo que ocupa en disco; el token es lo que ocupa **en la ventana del
modelo**, y es lo único que se compara con el contexto disponible. Dos documentos
del mismo KB pueden costar distinto según el idioma, el código y las tablas. Por
eso el criterio se mide en tokens y el KB se muestra sólo como comodidad
(`~x KB`), calculado con `CHARS_PER_TOKEN`.

Cuidado con el KB como unidad de decisión: **miente**. Un documento de 30 KB de
prosa española son ~9.400 tok; el mismo peso en tablas y rutas puede pasar de
12.000. El token no.

De dónde salen los números (medido, no supuesto)
------------------------------------------------
Referencia medida el 2026-10-29 en este desk con `granite_8b` (endpoint del
daemon, 10.240 tok de `n_ctx`):

    75.529 caracteres → 22.964 tokens   (3,29 car/tok)
    14.318 caracteres →  4.471 tokens   (3,20 car/tok)

Y dos correcciones de contexto que importan más que el umbral:

1. El **presupuesto real de prompt** no es `n_ctx`: es `n_ctx - 4096` (reserva de
   salida). Con 10.240 de ventana, el prompt útil son **6.144 tok**.
2. La ventana depende de la **compresión del KV cache**, no del modelo. Mismo
   `granite_8b` en la misma máquina: `f16` → 12.288 tok · `q8_0` → 24.576 ·
   `q4_0` → 49.152. Los umbrales de abajo están anclados al caso **conservador
   (`f16`)**; con KV comprimido el presupuesto es mayor y el criterio sigue
   siendo válido, sólo que exigente.

Con eso:

    ~2.000 tok  (~6-7 KB)   → documento cómodo de una sentada, junto a otros 2-3
    ~6.000 tok  (~19 KB)    → se come casi todo el prompt útil de una máquina
                              pequeña: ya no se compara, se hojea → dividir

⚠️ ESTO ES UNA HIPÓTESIS FECHADA, NO UNA LEY
--------------------------------------------
Los modelos avanzan y las técnicas también: lo que hoy ocupa un 9B, mañana lo
hace un 12B o un 27B en el mismo espacio. Por eso los números viven en las
constantes de abajo, con su fecha, y no dispersos:

- Si el objetivo pasa a modelos de 27B/30B, se suben ambos umbrales (y se
  actualiza la fecha de calibración).
- Si aparece una técnica de lectura por partes (RAG sobre el propio documento,
  chunking con índice), el umbral duro puede desaparecer y quedarse sólo el blando.
- **Nunca** cambies un número en mitad del código: son estas constantes o no es
  este criterio.

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

# ── CALIBRACIÓN (fecha: 2026-10-29) ──────────────────────────────────────────
# Cambiar SOLO aquí, y anotar la fecha y el modelo objetivo del cambio.
#
#   SOFT: documento que se lee entero junto a otros 2-3 y la pregunta, sin
#         quedarse sin ventana. ~1/3 del prompt útil medido (6.144 tok).
#   HARD: documento que se come casi todo el prompt útil por sí solo: ya no se
#         compara con nada, se hojea. Toca partirlo.
#
# Ancla conservadora: `granite_8b` con KV `f16` (la ventana más pequeña medida).
SOFT_LIMIT_TOKENS = 2_000
HARD_LIMIT_TOKENS = 6_000

# Caracteres por token, medido (no estimado): ver docstring. Sirve para enseñar el
# `~x KB` al lado del token. Si cambias de idioma mayoritario, vuelve a medirlo.
CHARS_PER_TOKEN = 3.2

CALIBRATED_ON = "2026-10-29"
CALIBRATED_FOR = "modelos locales pequeños (7B-9B) con KV f16 · prompt útil 6.144 tok"

# ── Exclusiones ─────────────────────────────────────────────────────────────
# Archivo histórico y bancos de memoria: crecen por diseño y no se leen enteros.
SKIP_DIR_PARTS = ("archive", "__pycache__", ".git", "node_modules")


def _human_pages(chars: int) -> float:
	"""Folios A4 técnicos estimados (~3.000 caracteres por página)."""
	return round(chars / 3000.0, 1)


def _scan(root: Path):
	"""Devuelve [(ruta, chars, tokens, KB)] de los .md bajo `root`, sin exclusiones."""
	out = []
	for p in root.rglob("*.md"):
		if any(part in SKIP_DIR_PARTS for part in p.parts):
			continue
		try:
			raw = p.read_bytes()
		except OSError:
			continue
		chars = len(raw.decode("utf-8", errors="ignore"))
		tokens = round(chars / CHARS_PER_TOKEN)
		out.append((p, chars, tokens, len(raw) / 1024.0))
	out.sort(key=lambda t: t[2], reverse=True)
	return out


def main() -> int:
	ap = argparse.ArgumentParser(description="Guardarraíl de tamaño de documento (en tokens; el KB es informativo).")
	ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Raíz a medir (default: planner/).")
	ap.add_argument("--strict", action="store_true", help="Falla también si se supera el umbral blando.")
	args = ap.parse_args()

	root = Path(args.root).expanduser().resolve()
	if not root.is_dir():
		print(f"[doc-size] raíz inexistente: {root}", file=sys.stderr)
		return 2

	docs = _scan(root)
	soft = [d for d in docs if d[2] > SOFT_LIMIT_TOKENS]
	hard = [d for d in docs if d[2] > HARD_LIMIT_TOKENS]

	print(f"[doc-size] raíz: {root}")
	print(f"[doc-size] calibración: {CALIBRATED_ON} · {CALIBRATED_FOR}")
	print(
		f"[doc-size] umbrales: blando {SOFT_LIMIT_TOKENS:,} tok "
		f"(~{SOFT_LIMIT_TOKENS * CHARS_PER_TOKEN / 1024:.0f} KB, índice obligatorio) · "
		f"duro {HARD_LIMIT_TOKENS:,} tok (~{HARD_LIMIT_TOKENS * CHARS_PER_TOKEN / 1024:.0f} KB, dividir)"
	)
	print(f"[doc-size] documentos: {len(docs)} · > blando: {len(soft)} · > duro: {len(hard)}")

	fmt = "  {tok:6,} tok  ~{kb:5.1f} KB  ~{pages:4.1f} pág  {rel}"

	if hard:
		print(f"\nSUPERAN EL UMBRAL DURO ({HARD_LIMIT_TOKENS:,} tok → dividir en sub-carpeta + índice):")
		for p, chars, tokens, kb in hard:
			print(fmt.format(tok=tokens, kb=kb, pages=_human_pages(chars), rel=p.relative_to(root)))

	rest = [d for d in soft if d[2] <= HARD_LIMIT_TOKENS]
	if rest:
		print(f"\nSUPERAN EL UMBRAL BLANDO ({SOFT_LIMIT_TOKENS:,} tok → deben llevar índice de secciones):")
		for p, chars, tokens, kb in rest[:20]:
			print(fmt.format(tok=tokens, kb=kb, pages=_human_pages(chars), rel=p.relative_to(root)))
		if len(rest) > 20:
			print(f"  … y {len(rest) - 20} más")

	if hard or (args.strict and soft):
		print("\n[doc-size] KO")
		return 1

	print("\n[doc-size] OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
