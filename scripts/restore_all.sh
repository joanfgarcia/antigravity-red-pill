#!/bin/bash
# restore_all.sh - Script de recuperación de Antigravity (User-Agnostic)

# Determinar la ruta base (IA_DIR)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IA_DIR="${ANTIGRAVITY_IA_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

show_help() {
    echo "Uso: bash restore_all.sh [completa|brain|qdrant]"
    echo "  completa: Reinstala Qdrant, restaura base de datos y archivos de alma."
    echo "  brain:    Solo restaura los archivos .md y scripts en el sistema."
    echo "  qdrant:   Solo restaura los snapshots en la base de datos vectorial."
}

# Encontrar la carpeta de backup más reciente
LATEST_SOUL=$(ls -td $IA_DIR/backups/soul/*/ | head -1)

# Encontrar dinámicamente dónde empieza el contenido del "home" en el backup
# (El backup se hizo con cp --parents, así que suele ser .../home/[usuario]/)
BACKUP_HOME_SRC=$(find "$LATEST_SOUL" -path "*/home/*" -type d -maxdepth 2 | head -1)

restore_qdrant_infra() {
    echo "--- Fase: Infraestructura Qdrant ---"
    if [ -z "$BACKUP_HOME_SRC" ]; then
        echo "ERROR: No se encontró estructura 'home' en el backup."
        return 1
    fi
    
    # El archivo qdrant.container debería estar en .config/containers/systemd/
    QDRANT_CONF=$(find "$BACKUP_HOME_SRC" -name "qdrant.container")
    
    if [ -f "$QDRANT_CONF" ]; then
        mkdir -p "$HOME/.config/containers/systemd"
        cp "$QDRANT_CONF" "$HOME/.config/containers/systemd/"
        echo "Contenedor Qdrant restablecido."
        
        # Recargar systemd
        systemctl --user daemon-reload
        systemctl --user start qdrant.service
        echo "Servicio Qdrant iniciado."
    else
        echo "AVISO: No se encontró qdrant.container en el backup."
    fi
}

restore_qdrant_data() {
    echo "--- Fase: Datos Vectoriales ---"
    BACKUP_QDRANT_DIR="$IA_DIR/backups/qdrant"
    if [ ! -d "$BACKUP_QDRANT_DIR" ]; then
        echo "Aviso: No existe el directorio de snapshots de Qdrant."
        return
    fi
    
    # Para cada snapshot, restaurar en Qdrant (esto requiere que qdrant esté corriendo)
    for SNAPSHOT in "$BACKUP_QDRANT_DIR"/*.snapshot; do
        if [ -f "$SNAPSHOT" ]; then
            COLL=$(basename "$SNAPSHOT" | cut -d'_' -f1,2)
            echo "Restaurando colección $COLL desde snapshot..."
            curl -X POST "http://localhost:6333/collections/$COLL/snapshots/upload" \
                 -H "Content-Type: multipart/form-data" \
                 -F "snapshot=@$SNAPSHOT"
        fi
    done
}

restore_soul_files() {
    echo "--- Fase: Archivos del Alma ---"
    if [ -z "$BACKUP_HOME_SRC" ]; then
        echo "ERROR: No se encontró carpeta 'home' en el backup."
        return 1
    fi
    
    echo "Sincronizando desde $BACKUP_HOME_SRC hacia $HOME ..."
    # rsync -av desde el interior de la carpeta del usuario del backup al home actual
    rsync -av "$BACKUP_HOME_SRC/" "$HOME/"
    echo "Archivos restaurados."
}

if [ -z "$1" ] || [ -z "$LATEST_SOUL" ]; then
    [ -z "$LATEST_SOUL" ] && echo "ERROR: No se encontraron backups en $IA_DIR/backups/soul"
    show_help
    exit 1
fi

case "$1" in
    completa)
        restore_qdrant_infra
        restore_soul_files
        restore_qdrant_data
        ;;
    brain)
        restore_soul_files
        ;;
    qdrant)
        restore_qdrant_data
        ;;
    *)
        show_help
        exit 1
        ;;
esac

echo "--- Proceso finalizado ---"
