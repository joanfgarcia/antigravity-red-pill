#!/bin/bash
set -e

echo "=== [STAGE 0] PREPARANDO ENTORNO BÜNKER (SCAFFOLDING) ==="

# 1. Simular la estructura base del IDE Antigravity (Requisito para los plugins)
echo "-> Creando estructura del IDE (.gemini/antigravity)..."
mkdir -p /home/aleth/.gemini/antigravity/brain
mkdir -p /home/aleth/.antigravity

echo "[OK] Entorno base inyectado en el Sandbox."
