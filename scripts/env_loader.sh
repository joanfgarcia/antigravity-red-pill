#!/bin/bash
# env_loader.sh - Resolución centralizada de rutas para Red Pill Protocol (v4.2.0)
# Esto soluciona (GM-001) y (DS-002) evitando divergencias en los cálculos de IA_DIR.

# El script que invoca este loader siempre define SCRIPT_DIR
# Calculamos IA_DIR asumiendo que este loader y los demás scripts viven en IA_DIR/scripts
if [ -z "${IA_DIR:-}" ]; then
    # Por si se ejecuta fuera de su carpeta nativa o al exportarlo
    _POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
    # Fallback legacy check
    if [[ "$_POTENTIAL_IA_DIR" != *"IA"* ]] && [[ "$_POTENTIAL_IA_DIR" != *"antigravity"* ]]; then
        _POTENTIAL_IA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
    fi
    export IA_DIR="${ANTIGRAVITY_IA_DIR:-$_POTENTIAL_IA_DIR}"
fi
