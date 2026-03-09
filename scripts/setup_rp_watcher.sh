#!/bin/bash
# Requerimientos: uv, python3.11+
set -e

echo "=== Configurando el Daemon del Vigía (RP-Watcher) ==="

DAEMON_DIR="$HOME/.agent/rp-watcher"
VENV_DIR="$DAEMON_DIR/.venv"
START_SCRIPT="$DAEMON_DIR/start.sh"

OS_NAME="$(uname -s)"

echo "[1/4] Detectando OS y creando el entorno aislado para RP-Watcher..."
mkdir -p "$DAEMON_DIR"

if [ ! -d "$VENV_DIR" ]; then
    uv venv "$VENV_DIR" --python 3.11
fi

echo "[2/4] Instalando dependencias del watcher..."
# plyer allows cross-platform notifications
uv pip install -p "$VENV_DIR" requests plyer cryptography

echo "[3/4] Creando script de arranque del Watcher..."
cat << 'START_EOF' > "$START_SCRIPT"
#!/bin/bash
export PATH="$HOME/.agent/rp-watcher/.venv/bin:$PATH"
source $HOME/.agent/rp-watcher/.venv/bin/activate

# Execute the swarm watcher Python script from the project source
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
export PYTHONPATH="_REPO_PATH_/src:$PYTHONPATH"
exec python3 _REPO_PATH_/src/red_pill/swarm/watcher.py
START_EOF

# Reemplazar la ruta del repositorio
REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)"
sed -i.bak "s|_REPO_PATH_|$REPO_PATH|g" "$START_SCRIPT"
rm -f "${START_SCRIPT}.bak"

chmod +x "$START_SCRIPT"

echo "[4/4] Generando el demonio del sistema para RP-Watcher..."
if [ "$OS_NAME" = "Darwin" ]; then
	PLIST_PATH="$HOME/Library/LaunchAgents/com.redpill.watcher.plist"
	cat << 'PLIST_EOF' > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.redpill.watcher</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>_HOME_/.agent/rp-watcher/start.sh</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>_HOME_/.agent/rp-watcher/error.log</string>
	<key>StandardOutPath</key>
	<string>_HOME_/.agent/rp-watcher/output.log</string>
</dict>
</plist>
PLIST_EOF
	sed -i.bak "s|_HOME_|$HOME|g" "$PLIST_PATH"
    rm -f "${PLIST_PATH}.bak"
	echo "  > Creado plist en $PLIST_PATH"
	
	launchctl unload "$PLIST_PATH" 2>/dev/null || true
	launchctl load "$PLIST_PATH"
else
	mkdir -p "$HOME/.config/systemd/user"
	SERVICE_PATH="$HOME/.config/systemd/user/rp-watcher.service"
	cat << 'SERVICE_EOF' > "$SERVICE_PATH"
[Unit]
Description=RP-Watcher (Red Pill Swarm Background Daemon)
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash _HOME_/.agent/rp-watcher/start.sh
Restart=always
StandardOutput=append:_HOME_/.agent/rp-watcher/output.log
StandardError=append:_HOME_/.agent/rp-watcher/error.log

[Install]
WantedBy=default.target
SERVICE_EOF
	sed -i "s|_HOME_|$HOME|g" "$SERVICE_PATH"
	echo "  > Creado systemd service en $SERVICE_PATH"
	
	systemctl --user daemon-reload
	systemctl --user enable rp-watcher.service
	systemctl --user restart rp-watcher.service
fi

echo "=== RP-Watcher Inyectado === "
echo "El proceso de notificaciones multi-agente está escuchando en background."
echo "Puedes comprobar el estado con: tail -f ~/.agent/rp-watcher/error.log"
