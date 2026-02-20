#!/bin/bash
# restore_all.sh - Script de recuperación de Antigravity (User-Agnostic)

# Administrar dry-run
DRY_RUN="--dry-run"
if [[ " $* " =~ " --commit " ]]; then
    DRY_RUN=""
fi

# Determinar la ruta base (IA_DIR) de forma segura
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/env_loader.sh" ]; then
    source "$SCRIPT_DIR/env_loader.sh"
else
    echo "ERROR Crítico: env_loader.sh no encontrado en $SCRIPT_DIR"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

show_help() {
    echo "Uso: bash restore_all.sh [completa|brain|qdrant] [--commit]"
    echo "  completa: Reinstala Qdrant, restaura base de datos y archivos de alma."
    echo "  brain:    Solo restaura los archivos .md y scripts en el sistema."
    echo "  qdrant:   Solo restaura los snapshots en la base de datos vectorial."
    echo "  --commit: Ejecuta los cambios destructivos reales (por defecto es DRY-RUN prudencial)."
}

# Encontrar la carpeta de backup más reciente
LATEST_SOUL=$(ls -td $IA_DIR/backups/soul/*/ | head -1)

# Encontrar dinámicamente dónde empieza el contenido del "home" en el backup
# (El backup se hizo con cp --parents, así que suele ser .../home/[usuario]/)
if [ -d "${LATEST_SOUL}home" ]; then
    BACKUP_HOME_SRC=$(find "${LATEST_SOUL}home" -mindepth 1 -maxdepth 1 -type d | head -1)
else
    BACKUP_HOME_SRC=""
fi

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
    if [ -n "$DRY_RUN" ]; then
        echo "🚨 MODO PRUDENCIAL ACTIVADO (DRY-RUN) 🚨"
        echo "Usa '--commit' si realmente deseas sobreescribir tus archivos."
    else
        echo "⚠️  EJECUTANDO RESTAURACIÓN REAL ⚠️"
    fi
    
    # GM-002: Safely target explicit component folders instead of raw host root
    echo "Sincronizando identidad (.agent/)..."
    rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.agent/" "$HOME/.agent/"
    
    echo "Sincronizando esencia (.gemini/antigravity/)..."
    rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.gemini/" "$HOME/.gemini/"
    
    echo "Sincronizando configs (.config/containers/)..."
    rsync -av $DRY_RUN "$BACKUP_HOME_SRC/.config/containers/" "$HOME/.config/containers/"
    
    echo "Archivos restaurados y desplegados con seguridad."
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
