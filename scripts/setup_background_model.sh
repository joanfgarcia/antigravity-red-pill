#!/bin/bash
# Requerimientos: uv, python3.11+, launchctl
set -e

echo "=== Configurando el Daemon del Modelo en Segundo Plano (Qwen3-30B) ==="

DAEMON_DIR="$HOME/.agent/model-daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/com.agent.modeldaemon.plist"
VENV_DIR="$DAEMON_DIR/.venv"
START_SCRIPT="$DAEMON_DIR/start.sh"

echo "[1/4] Creando el entorno B760 aislado..."
mkdir -p "$DAEMON_DIR"
uv venv "$VENV_DIR" --python 3.11
source "$VENV_DIR/bin/activate"
uv pip install mlx-lm

echo "[2/4] Creando script de arranque..."
cat << 'START_EOF' > "$START_SCRIPT"
#!/bin/bash
export PATH="$HOME/.agent/model-daemon/.venv/bin:$PATH"
source $HOME/.agent/model-daemon/.venv/bin/activate
exec mlx_lm.server --model lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-8bit --port 8760
START_EOF

chmod +x "$START_SCRIPT"

echo "[3/4] Generando el Plist de Launchctl..."
cat << 'PLIST_EOF' > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agent.modeldaemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>_HOME_/.agent/model-daemon/start.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>_HOME_/.agent/model-daemon/error.log</string>
    <key>StandardOutPath</key>
    <string>_HOME_/.agent/model-daemon/output.log</string>
</dict>
</plist>
PLIST_EOF

# Reemplazar la variable _HOME_ en el plist nativamente
sed -i '' "s|_HOME_|$HOME|g" "$PLIST_PATH"

echo "[4/4] Inyectando el demonio en la sesión activa..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "=== Daemon Inyectado === "
echo "El modelo MLX local se inicializará en segundo plano simulando una API de OpenAI en el puerto 8760."
echo "Puedes comprobar el estado con: tail -f ~/.agent/model-daemon/error.log"
