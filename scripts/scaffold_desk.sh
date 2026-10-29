#!/usr/bin/env bash
# Scaffold/refresh del desk desde seeds/desk (DESK-001 / RFC-ENLACES-001).
#
# DOS DUEÑOS:
#   - PUESTO  (contenido del Operador/agente): copy-if-absent — el seed NUNCA lo pisa.
#   - GERMEN  (tools/plantillas del runtime): el seed lo ACTUALIZA, con guard de hash.
# El manifiesto `seeds/desk/.germ` declara qué es germen.
#
# GERMEN: DOS POLÍTICAS, TRES HASHES
# ----------------------------------
# Comparar sólo desk-vs-seed_nuevo (como se hacía) revertía ediciones locales aunque
# el seed no hubiera cambiado nada. La decisión necesita TRES: base (lo que
# sembramos), cur (lo que hay), new (lo que traemos).
#
#   CÓDIGO (tools/**, *.py, *.sh…) — el seed manda SIEMPRE.
#     Diverge → se alinea con el seed. Si no se puede demostrar que el desk no lo
#     tocó (base ausente o distinta), se respalda primero y se dice en voz alta:
#     un parche local invisible es un fork que nadie sabe que existe.
#
#   PROSA (README, plantillas…) — el desk manda.
#     Diverge → NO se toca nunca. Si además hay novedad del seed, se deja al lado
#     como `*.seed-new` y se avisa: decide el agente. Sólo cuando el seed no ha
#     cambiado (base == new) se calla, porque no hay nada que ofrecer.
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

# Código vs prosa: decide qué política se aplica cuando el germen divergió.
# El código es del seed (no se parchea en local); la prosa es del desk.
CODE_RE='\.(py|sh|bash|js|mjs|cjs|ts)$'
is_code() { [[ "$1" =~ $CODE_RE ]]; }

say() { echo "[scaffold_desk] $*"; }
warn() { echo "[scaffold_desk] AVISO: $*" >&2; }

mkdir -p "$AGENT_CORE_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
BK="$AGENT_CORE_DIR/.germ.bak/$TS"
STATE_NEW="$(mktemp)"

# 1) Carpetas (siempre).
( cd "$SEED" && find . -type d ! -path './.git*' ! -path '*/__pycache__*' | sed 's|^\./||' ) | while IFS= read -r d; do
	[ -z "$d" ] || mkdir -p "$AGENT_CORE_DIR/$d"
done

# 2) Ficheros.
n_new=0 n_upd=0 n_same=0 n_local=0 n_rev=0 n_conf=0 n_unknown=0 n_keep=0 n_bk=0
while IFS= read -r rel; do
	[ -z "$rel" ] && continue
	[ "$rel" = ".germ" ] && continue
	src="$SEED/$rel"
	dst="$AGENT_CORE_DIR/$rel"
	newh="$(hash_of "$src")"
	[ -z "$newh" ] && continue

	# ── PUESTO: copy-if-absent. El seed nunca lo pisa.
	if ! is_germ "$rel"; then
		if [ ! -f "$dst" ]; then
			mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" && n_new=$((n_new + 1))
		else
			n_keep=$((n_keep + 1))
		fi
		continue
	fi

	# ── GERMEN: matriz de tres hashes (base / cur / new).
	if [ ! -f "$dst" ]; then
		mkdir -p "$(dirname "$dst")" && cp "$src" "$dst" && n_new=$((n_new + 1))
		printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
		continue
	fi

	curh="$(hash_of "$dst")"
	base="$(recorded_hash "$rel")"

	# (a) Idénticos: nada que hacer, y la base queda al día.
	if [ "$curh" = "$newh" ]; then
		n_same=$((n_same + 1))
		printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
		continue
	fi

	# (b) CÓDIGO: el seed manda siempre. Se respalda si no consta que esté intacto
	# (base ausente o distinta): un parche local invisible es un fork que nadie ve.
	if is_code "$rel"; then
		if [ "$base" = "$curh" ]; then
			n_upd=$((n_upd + 1)) # sólo novedad upstream: no había nada local
		else
			mkdir -p "$BK/$(dirname "$rel")" && cp "$dst" "$BK/$rel" && n_bk=$((n_bk + 1))
			warn "$rel: el código divergía del seed y se ha alineado. Si era un parche tuyo, está en $BK/$rel — el código no se parchea en local: mándalo al seed."
			n_rev=$((n_rev + 1))
		fi
		cp "$src" "$dst"
		printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
		continue
	fi

	# (c) PROSA: el desk manda. No se pisa nunca; si hay novedad, se deja al lado.
	if [ "$base" = "$curh" ]; then
		# El desk sigue igual que lo sembrado: la novedad es del seed. Se aplica.
		cp "$src" "$dst" && n_upd=$((n_upd + 1))
		printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
		continue
	fi
	if [ "$base" = "$newh" ]; then
		# El seed no ha cambiado: lo único que hay es trabajo del desk. Silencio.
		n_local=$((n_local + 1))
	elif [ -z "$base" ]; then
		# Aviso ÚNICO: se adopta el seed como base. La versión ofrecida no se aplica
		# (el desk manda en prosa), pero a partir de aquí las cuentas cuadran y no se
		# vuelve a avisar de lo mismo en cada instalación.
		n_unknown=$((n_unknown + 1))
		warn "$rel: sin registro de siembra previa y difiere del seed. Se conserva el del desk. Difiere a mano contra $src y, si no hay nada tuyo, cópialo."
		printf '%s\t%s\n' "$rel" "$newh" >> "$STATE_NEW"
		continue
	else
		n_conf=$((n_conf + 1))
		cp "$src" "$dst.seed-new"
		warn "$rel: cambiado en el desk y en el seed. Se conserva el del desk; la versión nueva queda en $rel.seed-new — decide y borra el .seed-new."
	fi
	# La base se conserva: si había conflicto, sigue vivo hasta que se resuelva.
	[ -n "$base" ] && printf '%s\t%s\n' "$rel" "$base" >> "$STATE_NEW"
done < <(cd "$SEED" && find . -type f ! -path './.git*' ! -path '*/__pycache__/*' \
	! -name '*.pyc' ! -name '*.pyo' ! -name '.DS_Store' | sed 's|^\./||' | sort)

mv "$STATE_NEW" "$STATE"
say "nuevos=$n_new actualizados=$n_upd intactos=$((n_same + n_keep)) locales=$n_local revertidos=$n_rev conflictos=$n_conf sin_registro=$n_unknown backups=$n_bk → $AGENT_CORE_DIR"
[ "$n_conf" -gt 0 ] && say "$n_conf conflicto(s) de prosa: la versión del seed queda al lado como *.seed-new (no se ha perdido nada)"
[ "$n_bk" -gt 0 ] && say "lo revertido/divergido está en $BK"

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
