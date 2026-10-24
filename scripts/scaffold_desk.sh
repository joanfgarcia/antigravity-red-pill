#!/usr/bin/env bash
# Scaffold/refresh del desk desde seeds/desk (DESK-001 / RFC-ENLACES-001).
#
# DOS DUEÑOS:
#   - PUESTO  (contenido del Operador/agente): copy-if-absent — el seed NUNCA lo pisa.
#   - GERMEN  (tools/plantillas del runtime): el seed lo ACTUALIZA, con guard de hash
#             (si el fichero divergió en el desk → backup + actualizar, no clobber).
# El manifiesto `seeds/desk/.germ` declara qué es germen.
#
# Uso: REPO_ROOT=<repo> AGENT_CORE_DIR=<desk> scripts/scaffold_desk.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$HERE/.." && pwd)}"
AGENT_CORE_DIR="${AGENT_CORE_DIR:?AGENT_CORE_DIR no definido}"
SEED="$REPO_ROOT/seeds/desk"
GERM_LIST="$SEED/.germ"
STATE="$AGENT_CORE_DIR/.germ.state"

if [ ! -d "$SEED" ]; then
	echo "[scaffold_desk] no existe $SEED" >&2
	exit 1
fi

hash_of() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

recorded_hash() { # rel → hash sembrado antes (o vacío)
	[ -f "$STATE" ] || return 0
	awk -F'\t' -v r="$1" '$1==r{print $2; exit}' "$STATE"
}

is_germ() { # rel → 0 si pertenece al germen
	local rel="$1" pat
	[ -f "$GERM_LIST" ] || return 1
	while IFS= read -r pat || [ -n "$pat" ]; do
		[ -z "$pat" ] && continue
		case "$rel" in
			$pat) return 0 ;;
		esac
	done < "$GERM_LIST"
	return 1
}

mkdir -p "$AGENT_CORE_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
BK="$AGENT_CORE_DIR/.germ.bak/$TS"
STATE_NEW="$(mktemp)"

# 1) Carpetas (siempre).
( cd "$SEED" && find . -type d ! -path './.git*' | sed 's|^\./||' ) | while IFS= read -r d; do
	[ -z "$d" ] || mkdir -p "$AGENT_CORE_DIR/$d"
done

# 2) Ficheros.
n_new=0 n_upd=0 n_bk=0 n_keep=0
while IFS= read -r rel; do
	[ -z "$rel" ] && continue
	[ "$rel" = ".germ" ] && continue
	src="$SEED/$rel"
	dst="$AGENT_CORE_DIR/$rel"
	newh="$(hash_of "$src")"
	[ -n "$newh" ] && printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
	if is_germ "$rel"; then
		if [ ! -f "$dst" ]; then
			mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" && n_new=$((n_new + 1))
		else
			curh="$(hash_of "$dst")"
			if [ "$curh" != "$newh" ]; then
				rech="$(recorded_hash "$rel")"
				if [ -n "$rech" ] && [ "$curh" != "$rech" ]; then
					# divergió en el desk: backup antes de actualizar
					mkdir -p "$BK/$(dirname "$rel")" && cp "$dst" "$BK/$rel" && n_bk=$((n_bk + 1))
				fi
				cp "$src" "$dst" && n_upd=$((n_upd + 1))
			fi
		fi
	else
		if [ ! -f "$dst" ]; then
			mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" && n_new=$((n_new + 1))
		else
			n_keep=$((n_keep + 1))
		fi
	fi
done < <(cd "$SEED" && find . -type f ! -path './.git*' | sed 's|^\./||' | sort)

mv "$STATE_NEW" "$STATE"
echo "[scaffold_desk] nuevos=$n_new actualizados=$n_upd backups=$n_bk intactos=$n_keep → $AGENT_CORE_DIR"
[ "$n_bk" -gt 0 ] && echo "[scaffold_desk] germen divergido respaldado en $BK"

# 3) Hook pre-commit del desk (RFC-ENLACES-001).
if [ -f "$AGENT_CORE_DIR/planner/tools/hooks/install.sh" ]; then
	if git -C "$AGENT_CORE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
		git -C "$AGENT_CORE_DIR" config core.hooksPath planner/tools/hooks
		chmod +x "$AGENT_CORE_DIR/planner/tools/hooks/pre-commit" 2>/dev/null || true
		echo "[scaffold_desk] hook pre-commit activado (core.hooksPath)"
	else
		echo "[scaffold_desk] desk sin git aún: engancha el hook con planner/tools/hooks/install.sh"
	fi
fi
