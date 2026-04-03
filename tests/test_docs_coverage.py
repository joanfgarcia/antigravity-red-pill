"""Test that every .md file under docs/ is reachable from docs/README.md.

Rule: A document is "reachable" if it is linked from docs/README.md directly,
OR linked from a document that IS linked from docs/README.md (2-hop max).
This ensures navigability — no orphan docs.
"""

import re
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
INDEX = DOCS_DIR / "README.md"

# Files/dirs we explicitly exclude from coverage checks
EXCLUDED = {
    "README.md",  # The index itself
}


def _extract_md_links(filepath: Path) -> set[Path]:
    """Extract all relative .md links from a markdown file."""
    links: set[Path] = set()
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return links

    # Match markdown links: [text](path.md) or [text](path/to/file.md)
    for match in re.finditer(r"\[.*?\]\(([^)]+\.md)\)", content):
        target = match.group(1)
        # Skip absolute URLs and anchors
        if target.startswith(("http://", "https://", "#")):
            continue
        resolved = (filepath.parent / target).resolve()
        if resolved.exists():
            links.add(resolved)
    return links


def test_all_docs_reachable_from_index():
    """Every .md file in docs/ must be reachable within 2 hops from docs/README.md."""
    # Collect all .md files under docs/
    all_docs = {
        p.resolve()
        for p in DOCS_DIR.rglob("*.md")
        if p.name not in EXCLUDED
    }

    # Hop 1: files linked directly from README.md
    hop1 = _extract_md_links(INDEX)

    # Hop 2: files linked from hop1 documents
    hop2: set[Path] = set()
    for doc in hop1:
        hop2.update(_extract_md_links(doc))

    reachable = hop1 | hop2

    orphans = all_docs - reachable
    if orphans:
        orphan_list = sorted(str(p.relative_to(DOCS_DIR)) for p in orphans)
        msg = (
            f"Found {len(orphan_list)} orphan doc(s) not reachable from docs/README.md:\n"
            + "\n".join(f"  - {o}" for o in orphan_list)
        )
        raise AssertionError(msg)


def test_no_broken_links_in_index():
    """Every link in docs/README.md must resolve to an existing file."""
    content = INDEX.read_text(encoding="utf-8")
    broken = []
    for match in re.finditer(r"\[.*?\]\(([^)]+\.md)\)", content):
        target = match.group(1)
        if target.startswith(("http://", "https://", "#")):
            continue
        resolved = (INDEX.parent / target).resolve()
        if not resolved.exists():
            broken.append(target)

    if broken:
        msg = (
            f"Found {len(broken)} broken link(s) in docs/README.md:\n"
            + "\n".join(f"  - {b}" for b in broken)
        )
        raise AssertionError(msg)
