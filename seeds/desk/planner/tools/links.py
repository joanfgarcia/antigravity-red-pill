#!/usr/bin/env python3
"""Enlaces entre documentos del desk (RFC-ENLACES-001).

Recorre Aleth_Core/, lee el frontmatter YAML y construye el grafo de referencias
tipadas (`related` / `depends_on` / `supersedes` / `superseded_by`): backlinks
DERIVADOS, referencias rotas (dangling), huérfanos y ciclos de `depends_on`.
On-demand (como `panel.py`), sin artefacto que envejezca.

Salida a stdout, o a fichero con `-o FILE`.

Reutiliza el parser de `panel.py` (misma carpeta).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from panel import ROOT, parse_frontmatter  # noqa: E402

REL_KEYS = ("related", "depends_on", "supersedes", "superseded_by")
ITEM_TYPES = {"rfc", "plan", "task", "note", "research", "audit", "spec", "lore", "log"}
SKIP_PREFIX = ".git"
SKIP_FILES = {"FRONTMATTER_TEMPLATE.md"}  # la plantilla usa rutas de ejemplo

# Baseline de refs rotas ACEPTADAS (las pre-existentes). `--check` solo grita por
# las NUEVAS (regresión), no por el ruido histórico. Ver RFC-ENLACES-001.
DEFAULT_BASELINE = Path(__file__).resolve().parent / ".links_baseline"

# Ref cross-repo: `<repo>: <ruta>` (p. ej. "red-pill: docs/…") → externa, no del desk.
CROSS_REPO = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]*:\s")


def _resolve(root: Path, origin: Path, ref: str) -> str | None:
	"""Resuelve una ruta del desk. El desk mezcla convenciones: se prueban
	relativa-al-fichero y relativa-a-la-raíz (la que exista gana). None si no
	resuelve (dangling)."""
	for base in (origin.parent, root):
		cand = (base / ref).resolve()
		try:
			rel = cand.relative_to(root.resolve()).as_posix()
		except ValueError:
			continue  # fuera del desk
		if cand.exists():
			return rel
	return None


def _link_values(fm: dict, key: str) -> list[str]:
	v = fm.get(key)
	if v is None:
		return []
	if isinstance(v, list):
		return [str(x).strip() for x in v if str(x).strip()]
	if isinstance(v, str) and v.strip():
		return [v.strip()]
	return []


def load_graph(root: Path = ROOT) -> dict[str, dict]:
	docs: dict[str, dict] = {}
	for p in sorted(root.rglob("*.md")):
		rel = p.relative_to(root).as_posix()
		if rel.startswith(SKIP_PREFIX) or p.name in SKIP_FILES:
			continue
		try:
			fm = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
		except OSError:
			continue
		if not fm.get("type"):
			continue  # sin frontmatter: fuera del grafo
		links: list[tuple[str, str, str | None]] = []
		for key in REL_KEYS:
			for dep in _link_values(fm, key):
				if dep.startswith(("http://", "https://", "#")) or CROSS_REPO.match(dep):
					continue  # externo (web o cross-repo): no es una arista del desk
				links.append((key, dep, _resolve(root, p, dep)))
		docs[rel] = {"path": p, "fm": fm, "links": links}
	return docs


def build_backlinks(docs: dict[str, dict]) -> dict[str, list[tuple[str, str]]]:
	back: dict[str, list[tuple[str, str]]] = {rel: [] for rel in docs}
	for rel, d in docs.items():
		for key, _dep, tgt in d["links"]:
			if tgt and tgt in back:
				back[tgt].append((rel, key))
	return back


def dangling(docs: dict[str, dict]) -> list[tuple[str, str, str]]:
	return [(rel, key, dep) for rel, d in docs.items() for key, dep, tgt in d["links"] if tgt is None]


def orphans(docs: dict[str, dict]) -> list[str]:
	linked: set[str] = set()
	for rel, d in docs.items():
		for _key, _dep, tgt in d["links"]:
			if tgt:
				linked.add(rel)
				linked.add(tgt)
	return [rel for rel, d in docs.items() if rel not in linked and d["fm"].get("type") in ITEM_TYPES]


def depends_cycles(docs: dict[str, dict]) -> list[list[str]]:
	edges = {rel: [t for k, _dep, t in d["links"] if k == "depends_on" and t] for rel, d in docs.items()}
	cycles: list[list[str]] = []
	temp: set[str] = set()
	done: set[str] = set()

	def visit(node: str, stack: list[str]) -> None:
		if node in done:
			return
		if node in temp:
			cycles.append(stack[stack.index(node) :] + [node])
			return
		temp.add(node)
		for nxt in edges.get(node, []):
			visit(nxt, stack + [nxt])
		temp.discard(node)
		done.add(node)

	for n in edges:
		visit(n, [n])
	return cycles


def _dangling_keys(docs: dict[str, dict]) -> set[str]:
	return {f"{rel}\t{key}\t{dep}" for rel, key, dep in dangling(docs)}


def load_baseline(path: Path) -> set[str]:
	try:
		return {ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
	except OSError:
		return set()


def save_baseline(path: Path, keys: set[str]) -> None:
	header = "# Refs rotas ACEPTADAS (RFC-ENLACES-001). Una por línea: rel<TAB>key<TAB>dep\n"
	path.write_text(header + "\n".join(sorted(keys)) + "\n", encoding="utf-8")


def render(docs: dict[str, dict]) -> str:
	back = build_backlinks(docs)
	dang = dangling(docs)
	orph = orphans(docs)
	cyc = depends_cycles(docs)
	edges = sum(len(d["links"]) for d in docs.values())

	out: list[str] = []
	out.append("# Enlaces entre documentos del desk")
	out.append("")
	out.append("_Generado por `planner/tools/links.py` (RFC-ENLACES-001). No editar a mano._")
	out.append("")
	out.append(f"Documentos con frontmatter: **{len(docs)}** · enlaces: **{edges}**.")
	out.append("")

	out.append("## Referencias rotas (dangling) — ERROR")
	out.append("")
	if dang:
		out.extend(f"- `{rel}` → `{key}: {dep}`" for rel, key, dep in dang)
	else:
		out.append("- (ninguna)")
	out.append("")

	out.append("## Ciclos de `depends_on` — AVISO")
	out.append("")
	if cyc:
		out.extend(f"- {' → '.join(c)}" for c in cyc)
	else:
		out.append("- (ninguno)")
	out.append("")

	out.append("## Backlinks (quién referencia a quién)")
	out.append("")
	for rel in sorted(docs):
		incoming = back.get(rel, [])
		if incoming:
			out.append(f"### {rel}")
			out.extend(f"- ← `{src}` ({key})" for src, key in sorted(incoming))
			out.append("")

	out.append("## Huérfanos (sin enlaces entrantes ni salientes) — AVISO")
	out.append("")
	if orph:
		out.extend(f"- `{rel}`" for rel in orph)
	else:
		out.append("- (ninguno)")
	out.append("")
	return "\n".join(out)


def main() -> int:
	ap = argparse.ArgumentParser(description="Grafo de enlaces del desk (RFC-ENLACES-001).")
	ap.add_argument("-o", "--output", help="Escribe el grafo a este fichero (por defecto stdout).")
	ap.add_argument("--check", action="store_true", help="Solo comprueba refs rotas NUEVAS vs baseline (exit 1 si las hay).")
	ap.add_argument("--update-baseline", action="store_true", help="Acepta las refs rotas actuales como baseline.")
	ap.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Ruta del fichero de baseline.")
	args = ap.parse_args()

	docs = load_graph()
	baseline_path = Path(args.baseline)

	if args.update_baseline:
		keys = _dangling_keys(docs)
		save_baseline(baseline_path, keys)
		print(f"[OK] baseline actualizada: {len(keys)} ref(s) rota(s) aceptada(s) → {baseline_path}")
		return 0

	if args.check:
		keys = _dangling_keys(docs)
		base = load_baseline(baseline_path)
		new = sorted(keys - base)
		resolved = sorted(base - keys)
		if resolved:
			print(f"[links] {len(resolved)} ref(s) rota(s) resuelta(s) — baja la baseline con --update-baseline")
		if new:
			print(f"[links] {len(new)} ref(s) rota(s) NUEVA(s):")
			for k in new:
				print("  - " + k.replace("\t", "  "))
			print("  → corrige, o acéptala con: links.py --update-baseline")
			return 1
		print("[links] sin refs rotas nuevas. OK")
		return 0

	text = render(docs)
	if args.output:
		Path(args.output).write_text(text, encoding="utf-8")
		print(f"[OK] {len(docs)} documento(s) → {args.output}")
	else:
		print(text)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
