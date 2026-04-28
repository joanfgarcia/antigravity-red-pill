#!/bin/bash
# Requerimientos: uv, python3.11+
set -e

echo "=== Configurando el Daemon del Modelo en Segundo Plano ==="

DAEMON_DIR="$HOME/.agent/model-daemon"
VENV_DIR="$DAEMON_DIR/.venv"
START_SCRIPT="$DAEMON_DIR/start.sh"

OS_NAME="$(uname -s)"

echo "[1/4] Detectando OS y creando el entorno aisladon..."
mkdir -p "$DAEMON_DIR"
uv venv "$VENV_DIR" --python 3.11
source "$VENV_DIR/bin/activate"

if [ "$OS_NAME" = "Darwin" ]; then
	echo "  > macOS (Darwin) detectado. Instalando mlx-lm..."
	uv pip install mlx-lm
else
	echo "  > Linux detectado. Instalando llama-cpp-python[server]..."
	uv pip install "llama-cpp-python[server]"
fi

echo "[2/4] Creando script de arranque..."
if [ "$OS_NAME" = "Darwin" ]; then
cat << 'START_EOF' > "$START_SCRIPT"
#!/bin/bash
export PATH="$HOME/.agent/model-daemon/.venv/bin:$PATH"
source $HOME/.agent/model-daemon/.venv/bin/activate
exec mlx_lm.server --model lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-8bit --port 8760
START_EOF
else
cat << 'DUAL_BIND_EOF' > "$DAEMON_DIR/run_dual_bind.py"
import os
import socket
import uvicorn
from llama_cpp.server.app import create_app, Settings

def main():
	settings = Settings(
		hf_model_repo_id="bartowski/Qwen2.5-7B-Instruct-GGUF",
		model="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
		chat_format="chatml",
		n_ctx=16384,
		n_gpu_layers=-1
	)
	app = create_app(settings)
	
	tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	tcp_sock.bind(("127.0.0.1", 8760))
	tcp_sock.listen()
	
	uds_path = os.path.expanduser("~/.agent/red_pill.sock")
	if os.path.exists(uds_path):
		os.remove(uds_path)
	uds_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	uds_sock.bind(uds_path)
	uds_sock.listen()
	os.chmod(uds_path, 0o600)
	
	config = uvicorn.Config(app=app, log_level="info")
	server = uvicorn.Server(config=config)
	
	import asyncio
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)
	loop.run_until_complete(server.serve(sockets=[tcp_sock, uds_sock]))

if __name__ == "__main__":
	main()
DUAL_BIND_EOF

cat << 'START_EOF' > "$START_SCRIPT"
#!/bin/bash
export PATH="$HOME/.agent/model-daemon/.venv/bin:$PATH"
source $HOME/.agent/model-daemon/.venv/bin/activate
# Utilizando Llama-cpp-python server con Dual-Bind (UDS Local + TCP Público).
exec python3 "$HOME/.agent/model-daemon/run_dual_bind.py"
START_EOF
fi

chmod +x "$START_SCRIPT"

echo "[3/4] Generando el demonio del sistema..."
if [ "$OS_NAME" = "Darwin" ]; then
	PLIST_PATH="$HOME/Library/LaunchAgents/com.agent.modeldaemon.plist"
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
	sed -i '' "s|_HOME_|$HOME|g" "$PLIST_PATH"
	echo "  > Creado plist en $PLIST_PATH"
else
	mkdir -p "$HOME/.config/systemd/user"
	SERVICE_PATH="$HOME/.config/systemd/user/red-pill-minion.service"
	cat << 'SERVICE_EOF' > "$SERVICE_PATH"
[Unit]
Description=Red Pill Minion LLM Daemon (llama.cpp)
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash _HOME_/.agent/model-daemon/start.sh
Restart=always
StandardOutput=append:_HOME_/.agent/model-daemon/output.log
StandardError=append:_HOME_/.agent/model-daemon/error.log

[Install]
WantedBy=default.target
SERVICE_EOF
	sed -i "s|_HOME_|$HOME|g" "$SERVICE_PATH"
	echo "  > Creado systemd service en $SERVICE_PATH"
fi

echo "[4/4] Inyectando el demonio en la sesión activa..."
if [ "$OS_NAME" = "Darwin" ]; then
	launchctl unload "$PLIST_PATH" 2>/dev/null || true
	launchctl load "$PLIST_PATH"
else
	systemctl --user daemon-reload
	systemctl --user enable red-pill-minion.service
	systemctl --user restart red-pill-minion.service
fi

echo "=== Daemon Inyectado === "
echo "El modelo local de fondo se inicializará simulando una API de OpenAI en el puerto 8760."
echo "Puedes comprobar el estado con: tail -f ~/.agent/model-daemon/error.log"
