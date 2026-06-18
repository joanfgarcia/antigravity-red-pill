#!/bin/bash
# Requerimientos: uv, python3.11+
#
# Architecture:
#   PERSISTENT_DIR ($XDG_DATA_HOME/red-pill/daemon) — survives reboots
#     ├── .venv/           (llama-cpp-python compiled env)
#     ├── run_dual_bind.py (dual-bind TCP+UDS server)
#     ├── start.sh         (daemon launcher)
#     ├── output.log
#     └── error.log
#
#   RUNTIME_DIR ($XDG_RUNTIME_DIR/red-pill) — volatile, per-boot
#     └── red_pill.sock    (UDS socket, created at runtime by run_dual_bind.py)
#
set -e

echo "=== Configurando el Daemon del Modelo en Segundo Plano ==="

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Persistent dir: survives reboot (venv, scripts, logs)
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PERSISTENT_DIR="$XDG_DATA_HOME/red-pill/daemon"

# Runtime dir: volatile, for socket only (correct per XDG spec)
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
	RUNTIME_DIR="$XDG_RUNTIME_DIR/red-pill"
else
	XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
	RUNTIME_DIR="$XDG_CACHE_HOME/red-pill/daemons"
fi

VENV_DIR="$PERSISTENT_DIR/.venv"
START_SCRIPT="$PERSISTENT_DIR/start.sh"

OS_NAME="$(uname -s)"

echo "[1/4] Detectando OS y creando el entorno aislado..."
mkdir -p "$PERSISTENT_DIR"
mkdir -p "$RUNTIME_DIR"

# Reuse existing venv if llama-cpp-python is already compiled
if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
	echo "  > Venv existente detectado en $VENV_DIR. Verificando..."
	if "$VENV_DIR/bin/python3" -c "import llama_cpp" 2>/dev/null; then
		echo "  > llama-cpp-python ya compilado. Saltando instalación."
		SKIP_INSTALL=1
	else
		echo "  > Venv incompleto. Re-instalando..."
		SKIP_INSTALL=0
	fi
else
	uv venv "$VENV_DIR"
	SKIP_INSTALL=0
fi

if [ "${SKIP_INSTALL:-0}" = "0" ]; then
	source "$VENV_DIR/bin/activate"
	if [ "$OS_NAME" = "Darwin" ]; then
		echo "  > macOS (Darwin) detectado. Instalando mlx-lm y dependencias..."
		uv pip install mlx-lm pyyaml psutil platformdirs
	else
		echo "  > Linux detectado. Instalando llama-cpp-python[server] y dependencias..."
		uv pip install "llama-cpp-python[server]" pyyaml psutil platformdirs
	fi
fi

echo "[2/4] Creando script de arranque..."
if [ "$OS_NAME" = "Darwin" ]; then
cat << 'START_EOF' > "$START_SCRIPT"
#!/bin/bash
export PATH="_PERSISTENT_DIR_/.venv/bin:$PATH"
export PYTHONPATH="_APP_ROOT_/src:$PYTHONPATH"
source _PERSISTENT_DIR_/.venv/bin/activate
exec mlx_lm.server --model lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-8bit --port 8760
START_EOF
else
cat << 'DUAL_BIND_EOF' > "$PERSISTENT_DIR/run_dual_bind.py"
import os
import socket
import uvicorn
from llama_cpp.server.app import create_app, Settings

def main():
	from red_pill.core.model_registry import ModelRegistry
	from red_pill.core.paths import resolve_model_path, get_daemon_dir

	profile_name = os.getenv("MINION_PROFILE", "samantha")
	profile = ModelRegistry.get_profile(profile_name)

	model_filename = profile.get("model_path", "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf")
	hf_repo_id = profile.get("hf_model_repo_id", None)

	# Resolve model path via paths.py
	model_path = str(resolve_model_path(os.path.basename(model_filename)))

	if os.path.exists(model_path):
		hf_repo_id_to_use = None
		model_param = model_path
	else:
		hf_repo_id_to_use = hf_repo_id
		model_param = model_filename

	# Resolve hardware affinity dynamically
	hardware = ModelRegistry.get_resolved_hardware_affinity(profile_name)

	settings = Settings(
		hf_model_repo_id=hf_repo_id_to_use,
		model=model_param,
		chat_format="chatml",
		n_ctx=hardware.get("n_ctx", profile.get("max_tokens", 4096)),
		n_gpu_layers=hardware.get("n_gpu_layers", -1)
	)
	app = create_app(settings)
	
	tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	tcp_sock.bind(("127.0.0.1", 8760))
	tcp_sock.listen()
	
	# Socket UDS en directorio de runtime (volátil, correcto por XDG spec)
	runtime_dir = str(get_daemon_dir())
	uds_path = os.path.join(runtime_dir, "red_pill.sock")
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
export PATH="_PERSISTENT_DIR_/.venv/bin:$PATH"
export PYTHONPATH="_APP_ROOT_/src:$PYTHONPATH"
source _PERSISTENT_DIR_/.venv/bin/activate
# Utilizando Llama-cpp-python server con Dual-Bind (UDS Local + TCP Público).
exec python3 "_PERSISTENT_DIR_/run_dual_bind.py"
START_EOF
fi

if [ "$OS_NAME" = "Darwin" ]; then
	sed -i '' "s|_APP_ROOT_|$APP_ROOT|g" "$START_SCRIPT"
	sed -i '' "s|_PERSISTENT_DIR_|$PERSISTENT_DIR|g" "$START_SCRIPT"
else
	sed -i "s|_APP_ROOT_|$APP_ROOT|g" "$START_SCRIPT"
	sed -i "s|_PERSISTENT_DIR_|$PERSISTENT_DIR|g" "$START_SCRIPT"
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
		<string>_PERSISTENT_DIR_/start.sh</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>Nice</key>
	<integer>19</integer>
	<key>LowPriorityIO</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>_PERSISTENT_DIR_/error.log</string>
	<key>StandardOutPath</key>
	<string>_PERSISTENT_DIR_/output.log</string>
</dict>
</plist>
PLIST_EOF
	sed -i '' "s|_PERSISTENT_DIR_|$PERSISTENT_DIR|g" "$PLIST_PATH"
	echo "  > Creado plist en $PLIST_PATH"
else
	mkdir -p "$HOME/.config/systemd/user"
	SERVICE_PATH="$HOME/.config/systemd/user/redpill-llm.service"
	cat << 'SERVICE_EOF' > "$SERVICE_PATH"
[Unit]
Description=Red Pill Sovereign Inference Proxy (BitNet)
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash _PERSISTENT_DIR_/start.sh
Restart=always
Nice=19
IOSchedulingClass=idle
StandardOutput=append:_PERSISTENT_DIR_/output.log
StandardError=append:_PERSISTENT_DIR_/error.log

[Install]
WantedBy=default.target
SERVICE_EOF
	sed -i "s|_PERSISTENT_DIR_|$PERSISTENT_DIR|g" "$SERVICE_PATH"
	echo "  > Creado systemd service en $SERVICE_PATH"
fi

echo "[4/4] Inyectando el demonio en la sesión activa..."
if [ "$OS_NAME" = "Darwin" ]; then
	launchctl unload "$PLIST_PATH" 2>/dev/null || true
	launchctl load "$PLIST_PATH"
else
	systemctl --user daemon-reload
	systemctl --user enable redpill-llm.service
	systemctl --user restart redpill-llm.service
fi

echo "=== Daemon Inyectado === "
echo "Artefactos persistentes en: $PERSISTENT_DIR"
echo "Socket de runtime en: $RUNTIME_DIR/red_pill.sock"
echo "El modelo local de fondo se inicializará simulando una API de OpenAI en el puerto 8760."
echo "Puedes comprobar el estado con: systemctl --user status redpill-llm.service"
