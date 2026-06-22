#!/bin/bash
set -e

echo "=========================================================="
echo "    [ SOVEREIGN SANDBOX: END-TO-END LIFECYCLE TEST ]      "
echo "=========================================================="

echo -e "\n[STAGE 1] Instalando Red-Pill en el Sandbox..."
pip install -e /opt/red-pill-src > /dev/null 2>&1

echo -e "\n[STAGE 2] Inicializando el Entorno (bunker init)..."
python -m red_pill.cli bunker init

echo -e "\n[STAGE 2.5] Instalando el Entorno (bunker install)..."
# Create dummy model file to skip HF download in sandbox
mkdir -p /home/aleth/.local/share/red-pill/models
touch /home/aleth/.local/share/red-pill/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
python -m red_pill.cli bunker install

echo -e "\n[STAGE 2.6] Sincronizando el Entorno (bunker update)..."
python -m red_pill.cli bunker update

echo -e "\n[STAGE 2.7] Verificando el Registro de Workspaces (pydantic round-trip)..."
# Exercises the install/update-critical path end-to-end in a real environment:
# manage_workspaces enable -> add_or_enable_workspace -> save_registry -> serialize,
# then `list` -> load_registry (pydantic validation). A registry/serialization
# regression fails the lifecycle here, not only in unit tests.
MW="/opt/red-pill-src/scripts/manage_workspaces.py"
WS_DIR="$(mktemp -d)"
WS_NAME="$(basename "$WS_DIR")"
printf '%s\n\n' "$WS_DIR" | python "$MW" enable
if python "$MW" list | grep -q "$WS_NAME"; then
    echo "[OK] Workspace registrado y validado (pydantic load_registry)."
else
    echo "[ERROR] El workspace no aparece en el registro tras 'enable'."
    exit 1
fi
python "$MW" disable "$WS_NAME"
if python "$MW" list | grep "$WS_NAME" | grep -q "sin acceso"; then
    echo "[OK] Acceso revocado (access:false) y re-validado."
else
    echo "[ERROR] 'disable' no reflejo 'sin acceso' para $WS_NAME."
    exit 1
fi
rm -rf "$WS_DIR"

echo -e "\n[STAGE 3] Inyectando Estado (Mock Data)..."
cat << 'EOF' > /tmp/inject_state.py
import os, sqlite3
from red_pill.core.paths import get_queue_dir, get_config_dir
queue_db = os.path.join(get_queue_dir(), "bunker_queue.db")
os.makedirs(os.path.dirname(queue_db), exist_ok=True)
conn = sqlite3.connect(queue_db)
conn.execute("CREATE TABLE IF NOT EXISTS cognitive_tasks (id TEXT PRIMARY KEY, payload TEXT)")
conn.execute("INSERT INTO cognitive_tasks VALUES ('test-01', 'dummy-data')")
conn.commit()
conn.close()

# Mocking .env
env_dir = get_config_dir()
os.makedirs(env_dir, exist_ok=True)
with open(os.path.join(env_dir, ".env"), "w") as f:
    f.write("TEST_SECRET=sovereign_test_123")
EOF
python /tmp/inject_state.py

echo -e "\n[STAGE 4] Exportando el Bünker (bunker export)..."
python -m red_pill.cli bunker export

echo -e "\n[STAGE 5] Desinstalando y Purgando (bunker uninstall)..."
# Usamos override para que no nos pida el código MFA de 6 dígitos en el test automático
export BUNKER_FORCE_UNINSTALL=1
python -m red_pill.cli bunker uninstall
unset BUNKER_FORCE_UNINSTALL

echo -e "\n[STAGE 6] Verificando la Purga..."
if [ -f "/home/aleth/.config/red-pill/.env" ]; then
    echo "[ERROR] El .env no fue eliminado."
    exit 1
fi
echo "[OK] Purga verificada. El estado fue aniquilado."

echo -e "\n[STAGE 7] Restaurando desde el Backup (bunker restore)..."
python -m red_pill.cli bunker restore

echo -e "\n[STAGE 8] Verificando la Rehidratación..."
if ! grep -q "TEST_SECRET=sovereign_test_123" "/home/aleth/.config/red-pill/.env"; then
    echo "[ERROR] El archivo .env no fue restaurado correctamente."
    exit 1
fi
echo "[OK] Estado recuperado perfectamente."

echo -e "\n=========================================================="
echo "      [ SUCCESS ] EL CICLO DEL SOUL KIT ES INFALIBLE      "
echo "=========================================================="
