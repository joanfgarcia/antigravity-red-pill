#!/bin/bash
# Instala el sidecar de etiquetado Laya (RFC-004) como unidad de usuario.
#
# Sustituye rutas (repo + venv) en la plantilla `systemd/redpill-laya-tag.service`
# y la despliega en `~/.config/systemd/user/`. NO arranca nada por sí solo si el
# modelo no está cacheado (la primera carga descarga ~650 MB de HF); pasa
# `--start` para habilitar y arrancar.
#
# Uso:
#   scripts/install_laya_tag_service.sh            # solo instala la unit
#   scripts/install_laya_tag_service.sh --start    # instala + enable --now
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYA_VENV="${LAYA_VENV:-$HOME/.local/share/red-pill/laya-venv}"
UNIT_SRC="$APP_ROOT/systemd/redpill-laya-tag.service"
UNIT_DST="$HOME/.config/systemd/user/redpill-laya-tag.service"

if [ ! -x "$LAYA_VENV/bin/python" ]; then
	echo "ERROR: venv de Laya no encontrado en $LAYA_VENV (¿instalaste torch+laya?)" >&2
	exit 1
fi

mkdir -p "$HOME/.config/systemd/user"
# La plantilla usa el especificador %h de systemd (válida tal cual con la
# disposición por defecto); aquí se fijan las rutas reales de esta máquina.
REPO_LITERAL="%h/Documents/IA/sharing"
VENV_LITERAL="%h/.local/share/red-pill/laya-venv"
sed -e "s|$REPO_LITERAL|$APP_ROOT|g" \
	-e "s|$VENV_LITERAL|$LAYA_VENV|g" \
	"$UNIT_SRC" > "$UNIT_DST"

systemctl --user daemon-reload
echo "Instalada: $UNIT_DST"

if [ "${1:-}" = "--start" ]; then
	systemctl --user enable --now redpill-laya-tag.service
	echo "Arrancada. Estado:"
	systemctl --user --no-pager status redpill-laya-tag.service | head -n 12 || true
	echo "Comprobación de salud:"
	"$LAYA_VENV/bin/python" "$APP_ROOT/scripts/laya_tag_server.py" --check || true
else
	echo "Para arrancar: systemctl --user enable --now redpill-laya-tag.service"
fi
