#!/usr/bin/env bash
# Instala el hook pre-commit del desk (RFC-ENLACES-001). Idempotente.
#
# En vez de copiar a `.git/hooks/` (no versionado), fija `core.hooksPath` a la
# carpeta versionada `planner/tools/hooks/` — así el hook viaja con el repo/seed.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
chmod +x "$ROOT/planner/tools/hooks/pre-commit"
git -C "$ROOT" config core.hooksPath planner/tools/hooks
echo "[OK] core.hooksPath=planner/tools/hooks — pre-commit del desk activo."
