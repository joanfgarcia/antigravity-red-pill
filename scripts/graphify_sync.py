#!/usr/bin/env python3
"""graphify_sync — reconcile per-project knowledge graphs across registry workspaces.

PoC core of AD-015. For each workspace with graphify:true, reconcile the git
repositories on disk against the workspace-local manifest (.graphify-projects.yaml):

  - enabled + changed (git HEAD moved, or no graph yet) -> `graphify update` (OOM-shielded)
  - enabled + unchanged                                 -> skip (cheap gate via stored HEAD)
  - disabled                                            -> skip
  - discovered but NOT in manifest                      -> report as NEW (operator classifies)
  - in manifest but gone from disk                      -> report as STALE

Change detection is git-HEAD based (robust for git repos) — `graphify check-update`
only flags pending *semantic* (clustering) re-extraction, not code changes. The
minion/timer/sentinel wrapping is phase 2; this is the testable core.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from red_pill.core import workspaces as ws  # noqa: E402

MANIFEST_NAME = ".graphify-projects.yaml"
MEM_MAX = os.environ.get("GRAPHIFY_MEM_MAX", "10G")


def _state_path() -> Path:
    try:
        from red_pill.core.paths import get_state_dir

        base = Path(get_state_dir())
    except Exception:
        base = Path(os.path.expanduser("~/.local/state/red-pill"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "graphify-state.yaml"


def _log(msg: str) -> None:
    """Append an audit line to the graphify-sync log (state dir)."""
    from datetime import datetime

    try:
        logp = _state_path().parent / "graphify-sync.log"
        with open(logp, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def _emit_failure(detail: str) -> None:
    """Best-effort pain signal so the Sentinel auto-heal loop can pick it up (heal_tissue)."""
    try:
        from red_pill.memory import MemoryManager

        MemoryManager().inject_signal(
            "knowledge_graph_stale", intensity=6.0, signal_type="pain", source="GRAPHIFY_SYNC"
        )
    except Exception as exc:
        print(f"[WARN] no se pudo emitir señal de fallo: {exc}", file=sys.stderr)
    _log(f"FAILURE: {detail}")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        print(f"[WARN] no se pudo leer {path}: {exc}", file=sys.stderr)
        return {}


def _discover_git_repos(root: Path) -> list:
    """Physical (no symlink-follow) find of git repos under root; paths RELATIVE to root."""
    try:
        out = subprocess.run(
            ["find", "-P", str(root), "-type", "d", "-name", ".git", "-prune"],
            capture_output=True, text=True, check=False,
        ).stdout
    except Exception:
        return []
    repos = []
    for line in out.splitlines():
        gitdir = Path(line.strip())
        if gitdir.name != ".git":
            continue
        try:
            repos.append(str(gitdir.parent.relative_to(root)))
        except ValueError:
            continue
    return sorted(repos)


def _git_head(proj: Path) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(proj), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=False)
        return r.stdout.strip() or None
    except Exception:
        return None


def sync(dry_run: bool = True, only: str | None = None) -> int:
    registry = ws.load_registry()
    targets = [w for w in registry.workspaces if w.graphify and (only is None or w.name == only)]
    if not targets:
        print("(sin workspaces con graphify:true)")
        return 0

    state = _load_yaml(_state_path())
    state_proj = state.setdefault("projects", {})
    actions: list[tuple[str, str]] = []

    for w in targets:
        root = w.root
        print(f"\n=== workspace '{w.name}' → {root} ===")
        if not root.exists():
            print("  [SKIP] root inexistente")
            continue
        manifest = _load_yaml(root / MANIFEST_NAME)
        listed = {p["path"]: bool(p.get("enabled", False))
                  for p in (manifest.get("projects") or [])
                  if isinstance(p, dict) and p.get("path")}
        discovered = set(_discover_git_repos(root))

        # 1) Manifest entries
        for path, enabled in listed.items():
            proj = root / path
            key = f"{w.name}:{path}"
            if not proj.exists():
                print(f"  [STALE] {path} — en manifiesto pero no en disco")
                actions.append((key, "stale"))
                continue
            if not enabled:
                print(f"  [skip]  {path} — disabled")
                continue
            head = _git_head(proj)
            last = (state_proj.get(key) or {}).get("last_head")
            graph = proj / "graphify-out" / "graph.json"
            if not graph.exists():
                reason = "sin grafo"
            elif last is None:
                reason = "sin estado previo"
            elif head != last:
                reason = "HEAD cambió"
            else:
                print(f"  [ok]    {path} — sin cambios (HEAD {head[:8] if head else 'n/a'}), skip")
                continue
            if dry_run:
                print(f"  [WOULD UPDATE] {path} — {reason}")
                actions.append((key, "would-update"))
            else:
                print(f"  [UPDATE] {path} — {reason}")
                cmd = ["systemd-run", "--user", "--scope", "-p", f"MemoryMax={MEM_MAX}",
                       "graphify", "update", str(proj), "--no-cluster"]
                rc = subprocess.run(cmd, check=False).returncode
                if rc == 0:
                    state_proj[key] = {"last_head": head, "path": str(proj)}
                    actions.append((key, "updated"))
                else:
                    print(f"  [ERROR] graphify update falló para {path} (rc={rc})")
                    actions.append((key, "error"))
                    _emit_failure(f"{key}: graphify update rc={rc}")

        # 2) New: discovered but unclassified
        for path in sorted(discovered - set(listed.keys())):
            print(f"  [NEW]   {path} — repo sin clasificar (¿habilitar en {MANIFEST_NAME}?)")
            actions.append((f"{w.name}:{path}", "new"))

    if not dry_run:
        with open(_state_path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(state, f, sort_keys=False)

    summary = dict(Counter(a[1] for a in actions))
    print(f"\n=== resumen: {len(actions)} acciones ===")
    for action, n in summary.items():
        print(f"  {action}: {n}")
    if not dry_run:
        _log(f"sync done (workspace={only or 'all'}): {summary}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconcilia y refresca los knowledge-graphs por proyecto (AD-015 PoC).")
    ap.add_argument("--dry-run", action="store_true", help="solo descubre/reporta; no ejecuta graphify ni escribe estado")
    ap.add_argument("--workspace", help="limitar a un workspace por nombre")
    args = ap.parse_args()
    sys.exit(sync(dry_run=args.dry_run, only=args.workspace))


if __name__ == "__main__":
    main()
