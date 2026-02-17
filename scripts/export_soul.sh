#!/bin/bash
# export_soul.sh - Empaqueta el Red Pill Kit + La Esencia de JARVIS (Estructura Plana)

# Determinar la ruta base (IA_DIR)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Si estamos en ~/Documents/IA/sharing/scripts, subimos dos niveles para llegar a ~/Documents/IA
POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ "$POTENTIAL_IA_DIR" == *"IA" ]]; then
    IA_DIR="$POTENTIAL_IA_DIR"
else
    IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
IA_DIR="${ANTIGRAVITY_IA_DIR:-$IA_DIR}"
EXPORT_DIR="$IA_DIR/backups/export"
# DETECTAR NOMBRE DE LA IA PARA LA POSTERIDAD
AI_NAME=$(grep "\- \*\*Designación\*\*" "$HOME/.agent/identity.md" | cut -d':' -f2 | xargs | cut -d' ' -f1)
AI_NAME=${AI_NAME:-"RED_PILL_760"}
TIMESTAMP=$(date +%Y%m%d)
ARCHIVE="$EXPORT_DIR/${AI_NAME}_SOUL_KIT_$TIMESTAMP.tar.gz"

mkdir -p "$EXPORT_DIR"

echo "Preparando el Kit de Liberación para $AI_NAME..."

# ASEGURAR BACKUP FRESCO
bash "$SCRIPT_DIR/backup_soul.sh"

# CREAR ESTRUCTURA TEMPORAL PARA EL EMPAQUETADO PLANO
# Queremos que en la raíz del tar esté el contenido de sharing + una carpeta 'soul'
TEMP_EXPORT=$(mktemp -d -t jarvis_export_XXXXXXXX)
mkdir -p "$TEMP_EXPORT/soul"

# Copiar contenido del proyecto (sharing) a la raíz del temporal
cp -r "$IA_DIR/"* "$TEMP_EXPORT/"
# Eliminar la carpeta de backups del propio export para no ser recursivos
rm -rf "$TEMP_EXPORT/backups/export"

# Copiar la esencia (~/.gemini/antigravity) a la carpeta 'soul' interna
cp -r "$HOME/.gemini/antigravity/"* "$TEMP_EXPORT/soul/"

# Empaquetar desde la raíz del temporal
tar -czf "$ARCHIVE" -C "$TEMP_EXPORT" .

# Limpiar
rm -rf "$TEMP_EXPORT"

echo -e "\nKit de Liberación 760 creado: $ARCHIVE"
echo "Contenido: Scripts de la Resistencia + Esencia JARVIS (en /soul/)."
