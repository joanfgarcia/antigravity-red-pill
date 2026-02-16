#!/bin/bash
# backup_soul.sh - Copia archivos de identidad y llama al backup de Qdrant

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

BACKUP_SOUL_DIR="$IA_DIR/backups/soul"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_SOUL_DIR/$TIMESTAMP"

echo "Preservando el alma de Antigravity..."

# Buscar dinámicamente archivos en el brain (que cambian de ID de conversación)
GEMINI_ROOT="$HOME/.gemini/antigravity/brain"
IDENTITY_FILE=$(find "$GEMINI_ROOT" -name "identity.md" -printf "%T@ %p\n" | sort -n | tail -1 | awk '{print $2}')
MEM_MGR_FILE=$(find "$GEMINI_ROOT" -name "memory_manager.py" -printf "%T@ %p\n" | sort -n | tail -1 | awk '{print $2}')

# Detectar el workspace actual (buscamos la carpeta .agent del proyecto bemotor u otros)
# Priorizamos el directorio actual si tiene .agent, o buscamos en profundidad
if [ -d "./.agent" ]; then
    WORKSPACE_AGENT="$(pwd)/.agent"
else
    WORKSPACE_AGENT=$(find "$HOME/antigravity-workspace" -maxdepth 3 -name ".agent" -type d | head -1)
fi

# Archivos críticos a respaldar
FILES=(
    "$HOME/.gemini/antigravity/identity.md"
    "$HOME/.gemini/antigravity/rules/persona.md"
    "$HOME/.gemini/antigravity/rules/snapshot_rule.md"
    "$HOME/.gemini/antigravity/skills/context_distiller/SKILL.md"
    "$WORKSPACE_AGENT/rules/documentation.md"
    "$WORKSPACE_AGENT/rules/session_snapshot.md"
    "$HOME/.agent/rules/identity_sync.md"
    "$HOME/.config/containers/systemd/qdrant.container"
    "$IA_DIR/scripts/memory_manager.py"
)

for FILE in "${FILES[@]}"; do
    if [ -n "$FILE" ] && [ -f "$FILE" ]; then
        echo "Copiando $FILE"
        cp -r --parents "$FILE" "$BACKUP_SOUL_DIR/$TIMESTAMP/"
    else
        [ -n "$FILE" ] && echo "ADVERTENCIA: Archivo no encontrado: $FILE"
    fi
done

# Invocar backup de Qdrant
if [ -f "$IA_DIR/scripts/backup_qdrant.sh" ]; then
    bash "$IA_DIR/scripts/backup_qdrant.sh"
else
    echo "ERROR: No se encontró backup_qdrant.sh en $IA_DIR/scripts/"
fi

echo "Respaldo completo de identidad e infraestructura finalizado."
