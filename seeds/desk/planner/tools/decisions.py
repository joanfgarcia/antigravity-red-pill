#!/usr/bin/env python3
"""Decision Closure Gate (P1-3) — ledger de decisiones de diseño del desk.

Determinista, sin LLM. Lee el frontmatter YAML de los `.md` del planner y resume
el ledger `decisions[]` (ver ``FRONTMATTER_TEMPLATE.md``).

    python3 planner/tools/decisions.py            # informe legible
    python3 planner/tools/decisions.py --check     # rc=1 si un `ratified` tiene
                                                   # una decisión `open` de blast
                                                   # >= medium (regla RFC_FLUJO §2.1)
    python3 planner/tools/decisions.py --json

Regla que comprueba: *el diseño está maduro cuando un modelo menos capaz puede
programarlo sin tomar ninguna decisión* (`RFC_DOSSIER_IDEACION §3.2`). Un ítem
`ratified` no puede tener huecos de diseño abiertos de impacto medio/alto.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FM_BLOCK = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)

OPEN = "open"
ACCEPTED = "accepted_default"
CLOSED = "closed"
RATIFIED = "ratified"
HIGH_BLAST = {"medium", "high"}


@dataclass
class Decision:
	id: str = ""
	question: str = ""
	status: str = OPEN
	chosen: str = ""
	default: str = ""
	blast_radius: str = "low"
	reversible: bool = True
	owner: str = ""


@dataclass
class DocLedger:
	path: str
	title: str = ""
	status: str = ""
	decisions: list[Decision] = field(default_factory=list)

	@property
	def open_decisions(self) -> list[Decision]:
		return [d for d in self.decisions if d.status in (OPEN, ACCEPTED)]


def _frontmatter(text: str) -> dict:
	m = FM_BLOCK.search(text)
	if not m:
		return {}
	try:
		data = yaml.safe_load(m.group(1)) or {}
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _decisions(raw: object) -> list[Decision]:
	if not isinstance(raw, list):
		return []
	out: list[Decision] = []
	for item in raw:
		if not isinstance(item, dict):
			continue
		out.append(
			Decision(
				id=str(item.get("id") or ""),
				question=str(item.get("question") or ""),
				status=str(item.get("status") or OPEN).strip().casefold(),
				chosen=str(item.get("chosen") or ""),
				default=str(item.get("default") or ""),
				blast_radius=str(item.get("blast_radius") or "low").strip().casefold(),
				reversible=bool(item.get("reversible", True)),
				owner=str(item.get("owner") or ""),
			)
		)
	return out


def scan(root: Path = ROOT) -> list[DocLedger]:
	"""Documentos del planner con ledger de decisiones (no vacío)."""
	base = Path(root) / "planner"
	if not base.is_dir():
		return []
	ledgers: list[DocLedger] = []
	for f in sorted(base.rglob("*.md")):
		if any(part.startswith(".") for part in f.parts):
			continue
		try:
			fm = _frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
		except Exception:
			continue
		decs = _decisions(fm.get("decisions"))
		if not decs:
			continue
		rel = f.relative_to(root) if str(f).startswith(str(root)) else f
		ledgers.append(
			DocLedger(
				path=str(rel),
				title=str(fm.get("title") or f.parent.name or f.stem),
				status=str(fm.get("status") or "").strip().casefold(),
				decisions=decs,
			)
		)
	return ledgers


def violations(root: Path = ROOT) -> list[tuple[DocLedger, Decision]]:
	"""`ratified` con decisión `open` de blast medio/alto — bloquea la ratificación."""
	bad: list[tuple[DocLedger, Decision]] = []
	for doc in scan(root):
		if doc.status != RATIFIED:
			continue
		for dec in doc.decisions:
			if dec.status == OPEN and dec.blast_radius in HIGH_BLAST:
				bad.append((doc, dec))
	return bad


def _report(ledgers: list[DocLedger], bad: list) -> str:
	lines = ["# Decision Closure Gate — ledger de decisiones", ""]
	if not ledgers:
		lines.append("_Sin ledgers `decisions:` en el planner (nada que comprobar)._")
		return "\n".join(lines)
	for doc in ledgers:
		lines.append(f"### {doc.path}  ·  `{doc.status}`")
		for d in doc.decisions:
			mark = {"closed": "✅", "accepted_default": "🟡", "open": "🔴"}.get(d.status, "·")
			extra = f" · default: {d.default}" if d.status == ACCEPTED and d.default else ""
			lines.append(f"- {mark} **{d.id}** [{d.status}/{d.blast_radius}] {d.question}{extra}")
		lines.append("")
	lines.append(f"**{len(bad)} violación(es)** (ratified con decisión open de blast ≥ medium).")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(description="Ledger de decisiones de diseño del desk (P1-3).")
	ap.add_argument("--check", action="store_true", help="rc=1 si hay violaciones de ratificación")
	ap.add_argument("--json", action="store_true", help="Salida JSON")
	ap.add_argument("--root", type=Path, default=ROOT, help="Raíz del desk")
	args = ap.parse_args()

	ledgers = scan(args.root)
	bad = violations(args.root)

	if args.json:
		print(
			json.dumps(
				{
					"ledgers": [
						{"path": d.path, "status": d.status, "decisions": [asdict(x) for x in d.decisions]}
						for d in ledgers
					],
					"violations": [{"path": d.path, "decision": asdict(x)} for d, x in bad],
				},
				ensure_ascii=False,
				indent=2,
			)
		)
	else:
		print(_report(ledgers, bad))
		if bad and not args.check:
			print("\n(usa --check para que un ítem `ratified` con huecos abiertos devuelva rc≠0)", file=sys.stderr)

	return 1 if (args.check and bad) else 0


if __name__ == "__main__":
	raise SystemExit(main())
