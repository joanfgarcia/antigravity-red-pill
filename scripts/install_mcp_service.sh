#!/usr/bin/env bash
# AD-018: instala/actualiza el backend MCP compartido (UDS) y lo deja activo.
# El proxy ligero lo lanza cada IDE; este servicio carga el kernel una sola vez.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
	echo "[MCP] no hay venv Python en $PY" >&2
	exit 1
fi

STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/red-pill/state"
SOCK="${REDPILL_MCP_SOCKET:-$STATE_DIR/mcp.sock}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$UNIT_DIR" "$STATE_DIR"
chmod 700 "$STATE_DIR" 2>/dev/null || true
sed -e "s|@REPO_ROOT@|$REPO_ROOT|g" \
	-e "s|@PYTHON@|$PY|g" \
	-e "s|@MCP_SOCKET@|$SOCK|g" \
	"$REPO_ROOT/systemd/redpill-mcp.service" > "$UNIT_DIR/redpill-mcp.service"

systemctl --user daemon-reload
systemctl --user enable redpill-mcp.service >/dev/null 2>&1 || true
systemctl --user restart redpill-mcp.service

for _ in $(seq 1 50); do
	[ -S "$SOCK" ] && break
	sleep 0.2
done
if [ -S "$SOCK" ]; then
	echo "[MCP] backend compartido activo: $SOCK"
else
	echo "[MCP] WARN: sin socket; revisa: systemctl --user status redpill-mcp.service" >&2
	systemctl --user --no-pager status redpill-mcp.service | tail -20 >&2 || true
	exit 1
fi
