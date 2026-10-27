#!/usr/bin/env python3
"""STATE.md — punto de entrada en frío del desk (P2-ARNES-004 §3.2).

Genera un snapshot determinista (sin LLM) que reúne, en un solo sitio:
- el panel activo (fases, prioridades, enlaces) — reutiliza `panel.py`;
- las **decisiones abiertas** del ledger — reutiliza `decisions.py`;
- los ítems **blocked/paused** con su `reason`.

Se **genera** (no se mantiene a mano): regenéralo tras cambios relevantes.
El digest OPEN LOOPS del handshake (kernel) cubre las notas/cola; aquí manda el desk.

Uso: python3 planner/tools/state.py [-o STATE.md]
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Reutiliza los parsers del panel (mismo árbol, misma verdad).
import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel  # noqa: E402

_FM = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)


def _blocked(docs: list) -> list[tuple[str, str, str]]:
	"""(ruta, status, reason) de los ítems blocked/paused."""
	out: list[tuple[str, str, str]] = []
	for d in docs:
		if d.status not in ("blocked", "paused"):
			continue
		try:
			text = d.path.read_text(encoding="utf-8")
			m = _FM.search(text)
			fm = (yaml.safe_load(m.group(1)) if m else {}) or {}
		except Exception:
			fm = {}
		out.append((d.rel, d.status, str(fm.get("reason") or "(sin reason ⚠)")))
	return sorted(out)


def build(root: Path = ROOT) -> str:
	docs = panel.load_docs(root)
	body = panel.render(docs, {"root": root}).rstrip()
	blocked = _blocked(docs)

	lines = [
		"---",
		"type: index",
		'title: "STATE.md — punto de entrada en frío (generado)"',
		"status: active",
		f"created: {date.today()}",
		"author: \"planner/tools/state.py (generado)\"",
		"project: aleth-core",
		"tags: [state, generado, entrada-fria]",
		"---",
		"",
		"> **Generado por `planner/tools/state.py`** — NO editar a mano; regenéralo.",
		"> El digest `OPEN LOOPS` del handshake cubre notas/cola; esto es el estado del desk.",
		"",
		body,
		"",
		"## 🚧 Bloqueados / paused",
		"",
	]
	if blocked:
		for rel, status, reason in blocked:
			lines.append(f"- `{rel}` · **{status}** — {reason}")
	else:
		lines.append("- (ninguno)")
	lines.append("")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(description="Genera STATE.md (entrada en frío del desk).")
	ap.add_argument("-o", "--output", default=str(ROOT / "STATE.md"), help="Fichero destino")
	ap.add_argument("--root", type=Path, default=ROOT)
	args = ap.parse_args()
	Path(args.output).write_text(build(args.root), encoding="utf-8")
	print(f"STATE.md escrito en {args.output}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
