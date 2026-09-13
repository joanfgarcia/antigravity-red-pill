#!/usr/bin/env python3
"""Desk panel generator (AGENT_CORE_DIR).

Recorre el desk (${AGENT_CORE_DIR})/, lee el frontmatter YAML de los .md y genera un panel de
seguimiento en markdown por stdout (o `-o FILE`). Sin fichero físico permanente:
el panel se genera cuando se pide.

La fase se deriva de la carpeta; el estado y la prioridad del frontmatter.
Ordena por fase, prioridad (High > Medium > Low) y depends_on (topológico).
Avisa de desajustes carpeta-vs-status.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]

PRIO_ORDER = {"High": 0, "Medium": 1, "Low": 2, "None": 3}

PHASE_DIRS = {
    "planner/ideas": "💡 Ideas",
    "planner/research": "🔬 Investigación",
    "planner/design": "📐 Diseño (RFCs)",
    "planner/pending": "⏳ Pendiente",
    "planner/in_progress": "🚧 En curso",
    "plans": "🗺️ Planes",
    "notes": "📝 Notas",
    "lore": "🕯️ Lore",
    "docs": "📚 Docs",
    "archive": "🗄️ Finalizado (archive)",
}

# estados cuyo lugar natural es una fase concreta del planner (carpeta vs frontmatter).
# Solo se avisa si el ítem vive en el planner y su status no cuadra con su fase.
STATUS_PHASE = {
    "spark": "planner/ideas",
    "llama": "planner/ideas",
    "maturing": "planner/research",
    "awaiting_operator": "planner/research",
    "parked": "planner/research",
    "dead": "planner/research",
    "superseded": "planner/research",
    "pending": "planner/pending",
    "in-progress": "planner/in_progress",
    "implemented": "planner/in_progress",
    "archived": "archive",
}

# rutas que se consideran "activo" (se muestran por defecto)
ACTIVE_PREFIXES = (
    "planner/ideas/",
    "planner/research/",
    "planner/design/",
    "planner/pending/",
    "planner/in_progress/",
    "plans/",
    "notes/",
    "lore/",
    "docs/",
)

FM_BLOCK = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)
YAML_KEY = re.compile(r"^([A-Za-z_][\w]*):\s*(.*)$")


@dataclass
class Doc:
    path: Path
    phase: str
    status: str = "unknown"
    priority: str = "None"
    title: str = ""
    type: str = ""
    project: str = ""
    depends_on: list[str] = field(default_factory=list)
    fm: dict = field(default_factory=dict)

    @property
    def rel(self) -> str:
        return str(self.path.relative_to(ROOT))


def parse_frontmatter(text: str) -> dict:
    """Parse a minimal YAML frontmatter block (flat keys, list values)."""
    m = FM_BLOCK.search(text)
    if not m:
        return {}
    fm: dict = {}
    key = None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            km = YAML_KEY.match(raw)
            if km:
                key, val = km.group(1), km.group(2).strip()
                if key in ("related", "depends_on", "tags"):
                    fm[key] = []
                else:
                    fm[key] = _scalar(val)
        elif key is not None and isinstance(fm.get(key), list):
            fm[key].append(_scalar(raw.strip().lstrip("- ").strip()))
    return fm


def _scalar(val: str):
    if not val:
        return ""
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    return val


def phase_of(path: Path) -> str:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    for pfx in ("planner/ideas", "planner/research", "planner/design",
                "planner/pending", "planner/in_progress"):
        if rel.as_posix().startswith(pfx):
            return pfx
    for top in ("plans", "notes", "lore", "docs", "archive"):
        if parts and parts[0] == top:
            return top
    return "root"


PHASE_README = {
    "planner/README.md",
    "planner/ideas/README.md",
    "planner/research/README.md",
    "planner/design/README.md",
    "planner/pending/README.md",
    "planner/in_progress/README.md",
}

SKIP_FILES = {
    "FRONTMATTER_TEMPLATE.md",  # referencia de convención, no un ítem
}


def load_docs(root: Path = ROOT) -> list[Doc]:
    docs: list[Doc] = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git") or rel in PHASE_README or rel in SKIP_FILES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if not fm.get("type"):
            continue  # sin frontmatter: no es un ítem del panel
        docs.append(
            Doc(
                path=p,
                phase=phase_of(p),
                status=str(fm.get("status", "unknown")),
                priority=str(fm.get("priority", "None")),
                title=str(fm.get("title", "")),
                type=str(fm.get("type", "")),
                project=str(fm.get("project", "")),
                depends_on=[str(x) for x in fm.get("depends_on", [])],
                fm=fm,
            )
        )
    return docs


def _resolve_target(root: Path, origin: Path, dep: str) -> Optional[Path]:
    if dep.startswith("/"):
        return None
    cand = (origin.parent / dep).resolve()
    if cand.exists():
        return cand
    return None


def topological(docs: list[Doc], root: Path) -> list[Doc]:
    """Orden topológico por depends_on (las dependencias antes)."""
    by_rel = {d.rel: d for d in docs}
    remaining = {d.rel: set() for d in docs}
    for d in docs:
        for dep in d.depends_on:
            target = _resolve_target(root, d.path, dep)
            if target is not None and target.resolve().relative_to(root).as_posix() in by_rel:
                remaining[d.rel].add(target.resolve().relative_to(root).as_posix())
    result: list[Doc] = []
    ready = sorted(
        [d for d in docs if not remaining[d.rel]],
        key=lambda x: (PRIO_ORDER.get(x.priority, 3), x.rel),
    )
    while ready:
        d = ready.pop(0)
        result.append(d)
        for rel in sorted(remaining):
            if d.rel in remaining[rel]:
                remaining[rel].discard(d.rel)
        ready = sorted(
            [dd for dd in docs if dd.rel in remaining and not remaining[dd.rel] and dd not in result],
            key=lambda x: (PRIO_ORDER.get(x.priority, 3), x.rel),
        )
    left = [d for d in docs if d not in result]
    return result + sorted(left, key=lambda x: x.rel)


def render(docs: list[Doc], filters: Optional[dict] = None) -> str:
    filters = filters or {}
    include_archive = filters.get("archive", False)
    out: list[str] = []
    out.append("# 🧠 Desk — Panel de seguimiento")
    out.append("")
    out.append(f"_Generado por `planner/tools/panel.py` · {__import__('datetime').date.today()}_")
    out.append("")

    ordered = topological(docs, ROOT)
    active = []
    archived = []
    for d in ordered:
        if filters.get("status") and d.status not in filters["status"]:
            continue
        if filters.get("project") and d.project != filters["project"]:
            continue
        if filters.get("priority") and d.priority != filters["priority"]:
            continue
        if filters.get("path") and not d.rel.startswith(filters["path"]):
            continue
        if d.rel.startswith("archive/"):
            archived.append(d)
        else:
            active.append(d)

    out.append("## 🟢 Activo")
    out.append("")
    _render_table(out, active)
    if include_archive:
        out.append("")
        out.append("## 🗄️ Finalizado (archive)")
        out.append("")
        _render_table(out, archived)
    else:
        out.append("")
        out.append(f"> _{len(archived)} ítems en archive/ no mostrados — usa `--archive` para ver lo finalizado._")
    out.append("")
    out.append("> La fase se deriva de la carpeta; mover un ítem = `git mv` entre fases.")
    out.append("> ⚠️ = desajuste carpeta-vs-status (revisar).")
    return "\n".join(out)


def _render_table(out: list[str], docs: list[Doc]) -> None:
    out.append("| Fase | Estado | Prioridad | Item | Enlace | Proyecto |")
    out.append("|---|---|---|---|---|---|")
    for d in docs:
        title = d.title or d.path.stem
        link = f"[{d.rel}]({d.rel})"
        phase = PHASE_DIRS.get(d.phase, d.phase)
        mismatch = ""
        if d.rel.startswith("planner/"):
            for st, expected in STATUS_PHASE.items():
                if d.status == st and expected not in d.rel:
                    mismatch = " ⚠️"
        out.append(f"| {phase} | `{d.status}`{mismatch} | {d.priority} | {title} | {link} | {d.project} |")


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera el panel del desk on-demand.")
    ap.add_argument("-o", "--output", help="Escribir a fichero en vez de stdout")
    ap.add_argument("--status", action="append", help="Filtrar por status (repetible)")
    ap.add_argument("--project", help="Filtrar por proyecto")
    ap.add_argument("--priority", choices=["High", "Medium", "Low"], help="Filtrar por prioridad")
    ap.add_argument("--path", help="Solo rutas que empiecen por este prefijo")
    ap.add_argument("--archive", action="store_true", help="Incluir lo finalizado (archive/)")
    ap.add_argument("--root", type=Path, default=ROOT, help="Raíz del desk")
    args = ap.parse_args()

    docs = load_docs(args.root)
    filters = {
        "status": args.status or None,
        "project": args.project,
        "priority": args.priority,
        "path": args.path,
        "archive": args.archive,
    }
    panel = render(docs, filters)
    if args.output:
        Path(args.output).write_text(panel, encoding="utf-8")
        print(f"Panel escrito en {args.output}")
    else:
        print(panel)
    return 0


if __name__ == "__main__":
    sys.exit(main())