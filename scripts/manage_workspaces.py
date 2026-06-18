#!/usr/bin/env python3
"""Operator-facing manager for the agent's workspace access (the single on/off switch).

ONE interactive routine, reused from install (install_neo.sh), update (upgrade.sh) and the
CLI. The operator sees a simple per-workspace on/off; underneath this writes the registry
(workspaces.yaml: access true/false) and re-syncs the per-surface permission adapters.

Today only the Claude Code adapter (inject_settings.py → additionalDirectories) is wired.
New IDE/CLI surfaces are drop-in: add their adapter; the switch and the registry don't change.

Subcommands:
  enable           Sequentially prompt for workspace(s) to grant access to (multiple allowed).
  disable <ws>     Revoke access (access:false). If the dir is gone, offer to delete the entry.
  list             Show registered workspaces + access state.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from red_pill.core import workspaces as ws  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

CAVEAT = (
    "Nota: 'access: false' = en modo AUTÓNOMO el agente NO podrá operar en ese workspace\n"
    "(sin acceso de archivos fuera del proyecto actual). Concede solo lo que necesites."
)

_YES = {"s", "si", "sí", "y", "yes"}


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _sync_claude(remove_dirs=None) -> None:
    """Re-sync the Claude Code permission adapter (inject_settings). On disable, remove only
    the given dirs; otherwise re-derive grants from the registry."""
    inject = os.path.join(SCRIPT_DIR, "inject_settings.py")
    if not os.path.exists(inject):
        return
    cmd = [sys.executable, inject]
    if remove_dirs:
        cmd.append("--remove")
        for d in remove_dirs:
            cmd += ["--extra-dir", d]
    try:
        subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] no se pudo sincronizar settings de Claude Code: {exc}", file=sys.stderr)


def cmd_list(_args) -> None:
    registry = ws.load_registry()
    if not registry.workspaces:
        print("(sin workspaces registrados)")
        return
    print("Workspaces registrados:")
    for w in registry.workspaces:
        mark = "✓ acceso" if w.access else "·  sin acceso"
        gone = "" if w.root.exists() else "   [ruta inexistente]"
        print(f"  {mark:14} {w.name:12} {w.root}{gone}")


def cmd_enable(args) -> None:
    print(CAVEAT, "\n")
    cmd_list(args)
    print(
        "\nIndica la ruta de cada workspace al que conceder acceso. Puedes añadir VARIOS,\n"
        "uno por línea. Enter en blanco para terminar.\n"
    )
    added = 0
    while True:
        raw = _ask("Ruta del workspace a habilitar (Enter para terminar): ")
        if not raw:
            break
        path = Path(os.path.expanduser(raw))
        if not path.exists():
            if _ask(f"  '{path}' no existe. ¿Añadir igualmente? (s/N): ").lower() not in _YES:
                print("  omitido.")
                continue
        _registry, w, was_new = ws.add_or_enable_workspace(str(path))
        print(f"  ✓ {'añadido' if was_new else 'habilitado'}: {w.name} → {w.root}")
        added += 1
    if added:
        _sync_claude()
        print(f"\n{added} workspace(s) con acceso. Permisos de Claude Code sincronizados.")
    else:
        print("\nSin cambios.")


def cmd_disable(args) -> None:
    w = ws.find_workspace(args.workspace)
    if not w:
        print(f"No encontrado en el registro: {args.workspace}", file=sys.stderr)
        sys.exit(1)
    remove_dirs = [str(w.root)] + ([str(w.atlas)] if w.atlas else [])
    if not w.root.exists():
        if _ask(f"'{w.root}' ya no existe. ¿Eliminar la entrada del registro? (s/N): ").lower() in _YES:
            ws.remove_workspace(w.name)
            _sync_claude(remove_dirs=remove_dirs)
            print(f"✓ eliminado del registro: {w.name}. Permisos retirados.")
            return
    ws.set_access(w.name, False)
    _sync_claude(remove_dirs=remove_dirs)
    print(f"✓ acceso revocado: {w.name}. Permisos retirados.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gestiona el acceso del agente a workspaces (registro red-pill)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("enable", help="prompt secuencial para conceder acceso a workspace(s)").set_defaults(func=cmd_enable)
    pd = sub.add_parser("disable", help="revocar acceso a un workspace (nombre o ruta)")
    pd.add_argument("workspace")
    pd.set_defaults(func=cmd_disable)
    sub.add_parser("list", help="listar workspaces y su estado de acceso").set_defaults(func=cmd_list)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
