#!/usr/bin/env python3
"""A-4 (AWAKEN-002): pre-pase determinista de estados del planner.

Sin LLM. Lee el frontmatter (`id`, `status`) de los documentos del planner del
desk y lo compara con la evidencia real en los repos git (ramas, commits y
ficheros que mencionan el id). Emite una lista de DISCREPANCIAS propuestas —
nunca aplica cambios.

El despertar (o el operador) revisa solo lo marcado: un draft con rama/commit es
candidato a `in-progress`; un `implemented` sin merge, un `closed` sin evidencia o
un `blocked`/`paused` sin `reason` son banderas.

Uso:
uv run python scripts/planner_state_audit.py
uv run python scripts/planner_state_audit.py --repo ~/src/neon-link --json
uv run python scripts/planner_state_audit.py --only AWAKEN-002 --strict
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
	sys.path.insert(0, str(REPO_ROOT / "src"))

from red_pill.core.awakening_channel import parse_frontmatter  # noqa: E402

NEEDS_REASON = {"blocked", "paused"}
IMPLEMENTATION_STATUSES = {"in-progress", "implemented", "closed", "archived"}
NO_EVIDENCE_STATUSES = {"in-progress", "implemented", "closed"}
_ID_LIKE = re.compile(r"[A-Za-z].*[0-9]")
_GENERIC_STEMS = {"readme", "index", "design", "descripcion", "notas", "notes"}


def _token_for(doc: Path, fm: dict) -> str:
	"""Token buscable en git. `id` del frontmatter manda; si no, el stem (o la
	carpeta padre si el stem es genérico). Tokens genéricos sin dígito → "" (no
	se busca evidencia: ensuciaría con matches irrelevantes)."""
	tid = str(fm.get("id") or "").strip()
	if tid:
		return tid
	candidate = doc.parent.name if doc.stem.lower() in _GENERIC_STEMS else doc.stem
	return candidate if _ID_LIKE.search(candidate) else ""


def _git(repo: Path, *args: str) -> list[str]:
	try:
		out = subprocess.run(
			["git", "-C", str(repo), *args],
			capture_output=True, text=True, timeout=30, check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return []
	if out.returncode != 0:
		return []
	return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _git_root(path: Path) -> Path | None:
	lines = _git(path, "rev-parse", "--show-toplevel")
	return Path(lines[0]) if lines else None


def _scanner_docs(planner_root: Path) -> list[Path]:
	docs: list[Path] = []
	for f in sorted(planner_root.rglob("*.md")):
		if any(part.startswith(".") for part in f.parts):
			continue
		docs.append(f)
	docs += sorted(planner_root.glob("*.md"))
	return sorted(set(docs))


def _evidence(repos: list[Path], token: str, max_commits: int) -> dict:
	branches: list[str] = []
	commits: list[str] = []
	merges: list[str] = []
	files: list[str] = []
	for repo in repos:
		branches += [f"{repo.name}:{b}" for b in _git(repo, "branch", "-a", "--list", f"*{token}*")]
		commits += [f"{repo.name}:{c}" for c in _git(repo, "log", "--all", "-i", "--oneline", f"--grep={token}", f"-n{max_commits}")]
		merges += [f"{repo.name}:{c}" for c in _git(repo, "log", "--all", "-i", "--merges", "--oneline", f"--grep={token}", f"-n{max_commits}")]
		files += [f"{repo.name}:{p}" for p in _git(repo, "ls-files", f"*{token}*")]
	return {"branches": branches, "commits": commits, "merges": merges, "files": files}


def _propose(status: str, ev: dict, has_reason: bool, has_token: bool = True) -> list[dict]:
	status = (status or "").strip().lower()
	out: list[dict] = []
	has_impl_evidence = bool(ev["commits"] or ev["files"])
	if status in NEEDS_REASON and not has_reason:
		out.append({"kind": "missing-reason", "severity": "high", "suggest": status, "reason": f"`{status}` exige `reason` en el frontmatter"})
	if not has_token:
		return out
	if status == "draft" and has_impl_evidence:
		out.append({
			"kind": "stale-status", "severity": "medium",
			"suggest": "in-progress",
			"reason": "draft sin evidencia de trabajo, pero hay rama/commit/fichero",
		})
	if status == "ready" and has_impl_evidence:
		out.append({"kind": "stale-status", "severity": "medium", "suggest": "in-progress", "reason": "ready con trabajo ya iniciado"})
	if status == "in-progress" and ev["merges"]:
		out.append({"kind": "advance", "severity": "medium", "suggest": "implemented", "reason": "merge(s) que mencionan el id"})
	if status in NO_EVIDENCE_STATUSES and not has_impl_evidence and not ev["branches"]:
		out.append({"kind": "no-evidence", "severity": "high", "suggest": "draft", "reason": f"{status} sin rama/commit/fichero verificable"})
	if status == "closed" and not ev["merges"]:
		out.append({"kind": "unverified-closed", "severity": "high", "suggest": status, "reason": "closed sin merge verificable"})
	return out


def audit(desk: Path, repos: list[Path], only: str | None = None, max_commits: int = 40) -> list[dict]:
	planner = Path(desk) / "planner"
	if not planner.is_dir():
		return []
	results: list[dict] = []
	for doc in _scanner_docs(planner):
		try:
			fm, _ = parse_frontmatter(doc.read_text(encoding="utf-8"))
		except OSError:
			continue
		if not fm:
			continue
		status = str(fm.get("status") or "").strip()
		if not status:
			continue
		token = _token_for(doc, fm)
		if only and token.casefold() != only.casefold():
			continue
		has_reason = any(fm.get(k) for k in ("reason", "blocked_reason", "paused_reason"))
		ev = _evidence(repos, token, max_commits) if token else {"branches": [], "commits": [], "merges": [], "files": []}
		props = _propose(status, ev, has_reason, has_token=bool(token))
		if props:
			results.append({
				"doc": str(doc),
				"id": token or doc.stem,
				"status": status,
				"evidence": ev,
				"proposals": props,
			})
	return results


def render_markdown(results: list[dict], desk: Path, repos: list[Path]) -> str:
	lines = [
		"# Pre-pase determinista de estados del planner (AWAKEN-002 · A-4)",
		"",
		f"- Desk: `{desk}`",
		"- Repos: " + (", ".join(f"`{r}`" for r in repos) or "_(ninguno)_"),
		"",
	]
	if not results:
		lines.append("Sin discrepancias. Nada que proponer.")
		return "\n".join(lines)
	for r in results:
		lines.append(f"## {r['id']} — `{r['status']}` → {', '.join(p['suggest'] for p in r['proposals'])}")
		lines.append(f"`{r['doc']}`")
		for p in r["proposals"]:
			lines.append(f"- **{p['kind']}** ({p['severity']}): {p['reason']} → propone `{p['suggest']}`")
		ev = r["evidence"]
		for key, label in (("branches", "rama(s)"), ("commits", "commit(s)"), ("merges", "merge(s)"), ("files", "fichero(s)")):
			if ev[key]:
				lines.append(f"  - {label}: " + ", ".join(f"`{x}`" for x in ev[key][:5]))
		lines.append("")
	lines.append("> Propuestas, no órdenes: el despertar/el operador decide. Nada se ha aplicado.")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(description="Pre-pase determinista de estados del planner (AWAKEN-002 A-4).")
	ap.add_argument("--desk", default=None, help="Raíz del desk (default: AGENT_CORE_DIR).")
	ap.add_argument("--repo", action="append", default=[], help="Repo git a inspeccionar (repetible).")
	ap.add_argument("--only", default=None, help="Solo un id concreto.")
	ap.add_argument("--max-commits", type=int, default=40)
	ap.add_argument("--json", action="store_true", help="Salida JSON.")
	ap.add_argument("--strict", action="store_true", help="Exit 1 si hay discrepancias.")
	args = ap.parse_args()

	desk = Path(args.desk) if args.desk else _default_desk()
	repos: list[Path] = [Path(r).expanduser().resolve() for r in args.repo if Path(r).expanduser().is_dir()]
	if not args.repo:
		root = _git_root(Path.cwd())
		if root:
			repos.append(root)

	results = audit(desk, repos, only=args.only, max_commits=args.max_commits)
	if args.json:
		print(json.dumps({"desk": str(desk), "repos": [str(r) for r in repos], "results": results}, ensure_ascii=False, indent=2))
	else:
		print(render_markdown(results, desk, repos))
	return 1 if (args.strict and results) else 0


def _default_desk() -> Path:
	try:
		from red_pill.core.paths import get_agent_core_root

		return get_agent_core_root()
	except Exception:
		return Path.cwd()


if __name__ == "__main__":
	sys.exit(main())
