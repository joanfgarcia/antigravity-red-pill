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
import sys
import socket
import signal
import subprocess
import shutil
import math
import argparse
import uvicorn
import time
import asyncio
import gc
import logging
import json
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Configuración básica de logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [DUAL_BIND] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Red Pill Dynamic Inference Proxy")

# Configuración global del modelo al importar
from red_pill.core.model_registry import ModelRegistry
from red_pill.core.paths import resolve_model_path

PROFILE_NAME = os.getenv("MINION_PROFILE", "samantha")
PROFILE = ModelRegistry.get_profile(PROFILE_NAME)
MODEL_FILENAME = PROFILE.get("model_path", "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf")
MODEL_BASENAME = os.path.basename(MODEL_FILENAME)
CHAT_FORMAT = PROFILE.get("chat_format", "chatml")
# Minion mode: a request carrying tools/functions switches the chat handler to a
# function-calling formatter so Granite emits OpenAI-style tool_calls. Distiller and
# plain requests keep the profile default (CHAT_FORMAT) untouched — same loaded model.
MINION_CHAT_FORMAT = PROFILE.get("minion_chat_format", "chatml-function-calling")


def _resolve_chat_format(body: Dict[str, Any]) -> str:
	explicit = body.get("chat_format")
	if explicit:
		return explicit
	if body.get("tools") or body.get("functions"):
		return MINION_CHAT_FORMAT
	return CHAT_FORMAT

# Resolve model path
MODEL_PATH = str(resolve_model_path(MODEL_BASENAME))
HF_REPO_ID = PROFILE.get("hf_model_repo_id", None)

# Device fallback cascade.
# Ordered device preference. The backend tries each in turn; the first that can
# serve wins. If none can, the request fails (503) — no implicit fallback beyond
# what the list declares. A request may override this via body["device_fallback"].
#   gpu  -> in-process llama.cpp with GPU offload (fast path, unchanged)
#   cpu  -> isolated worker subprocess, CUDA detached, under an OOM shield
#   igpu -> Vulkan/unified-memory (NOT wired yet; skipped with a warning)
#   npu  -> FastFlowLM NPU (NOT wired for these models yet; skipped)
DEFAULT_DEVICE_FALLBACK = ["gpu", "cpu"]
DEVICE_FALLBACK = PROFILE.get("device_fallback", DEFAULT_DEVICE_FALLBACK)
# CPU context is sized to RAM, independent of the VRAM tiers (a 16k KV fits easily
# in system RAM even though it would never fit alongside the model on an 8 GB card).
CPU_N_CTX = int(PROFILE.get("cpu_n_ctx", PROFILE.get("hardware_affinity", {}).get("n_ctx", PROFILE.get("max_tokens", 4096))))

CPU_WORKER_PORT = int(os.getenv("CPU_WORKER_PORT", "8761"))
IS_CPU_WORKER = os.getenv("MINION_CPU_WORKER") == "1"
FORCED_NCTX = int(os.getenv("CPU_WORKER_NCTX", "0")) or None
# Empirical footprint (Granite-4.1-8B-Q4, use_mmap=false): base ~8.8 GB + ~0.15 MB/token KV.
_CPU_BASE_GB = 9.0
_CPU_KV_MB_PER_TOKEN = 0.16


def _cpu_shield_gb(n_ctx: int) -> int:
	return math.ceil((_CPU_BASE_GB + (n_ctx * _CPU_KV_MB_PER_TOKEN) / 1024.0) * 1.15)


def _cpu_worker_unit() -> str:
	return f"redpill-cpu-worker-{CPU_WORKER_PORT}"

# Control de inactividad
DEFAULT_HIGH_TIMEOUT = 300  # 5 minutos para tareas normales/interactivas
DEFAULT_LOW_TIMEOUT = 10    # 10 segundos para tareas de baja prioridad (sleep cycle, etc.)


class BackendUnavailable(RuntimeError):
	"""No device in the fallback cascade could serve the request."""


class ModelManager:
	def __init__(self):
		self.model = None          # in-process (GPU or worker-local) Llama
		self.worker = None         # subprocess.Popen of the CPU worker (parent only)
		self.worker_port = None
		self.mode = None           # "gpu" | "cpu" | None
		self.n_ctx = None
		self.lock = asyncio.Lock()
		self.last_active = time.time()
		self.last_priority = "high"

	async def ensure_backend_under_lock(self, prefs: Optional[List[str]] = None):
		self.last_active = time.time()
		if self.mode is not None:
			return

		# A CPU worker process always loads its model in-process (CUDA is already
		# hidden by the parent's env). It never re-enters the cascade.
		if IS_CPU_WORKER:
			self._load_in_process(FORCED_NCTX or CPU_N_CTX, 0)
			return

		cascade = prefs or DEVICE_FALLBACK or DEFAULT_DEVICE_FALLBACK
		errors = []
		for device in cascade:
			try:
				if device == "gpu":
					hardware = ModelRegistry.get_resolved_hardware_affinity(PROFILE_NAME)
					n_gpu_layers = hardware.get("n_gpu_layers", -1)
					if n_gpu_layers == 0:
						errors.append("gpu: insufficient free VRAM")
						continue
					self._load_in_process(hardware.get("n_ctx", PROFILE.get("max_tokens", 4096)), n_gpu_layers)
					return
				elif device == "cpu":
					self._start_cpu_worker(CPU_N_CTX)
					return
				elif device in ("igpu", "npu"):
					logger.warning(f"Device '{device}' requested but not wired for {MODEL_BASENAME} yet; skipping.")
					errors.append(f"{device}: not implemented")
					continue
				else:
					errors.append(f"{device}: unknown device")
					continue
			except Exception as e:
				logger.error(f"Device '{device}' failed to come up: {e!r}")
				errors.append(f"{device}: {e}")
				continue

		raise BackendUnavailable(f"No usable device in preference {cascade}: {errors}")

	def _load_in_process(self, n_ctx, n_gpu_layers):
		where = "CPU worker" if IS_CPU_WORKER else "GPU/in-process"
		logger.info(f"Loading model ({where}): {MODEL_BASENAME} (GPU layers: {n_gpu_layers}, Context: {n_ctx})")
		from llama_cpp import Llama
		self.model = Llama(
			model_path=MODEL_PATH,
			chat_format=CHAT_FORMAT,
			n_ctx=n_ctx,
			n_gpu_layers=n_gpu_layers,
			verbose=False,
		)
		self.mode = "cpu" if IS_CPU_WORKER else "gpu"
		self.n_ctx = n_ctx
		logger.info(f"Model {MODEL_BASENAME} successfully loaded ({where}).")

	def _start_cpu_worker(self, n_ctx):
		shield = _cpu_shield_gb(n_ctx)
		# GPU is the preferred path; falling back to CPU is a real degradation (much
		# slower, higher RAM pressure) so it is logged at WARNING for visibility.
		logger.warning(
			f"GPU unavailable for {MODEL_BASENAME}: falling back to CPU inference "
			f"(n_ctx={n_ctx}, OOM shield={shield}G). CPU is markedly slower than GPU."
		)
		unit = _cpu_worker_unit()
		# Clean any stale scope from a previous crash so the named unit is free.
		if shutil.which("systemctl"):
			subprocess.run(["systemctl", "--user", "reset-failed", f"{unit}.scope"],
				stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		env = dict(os.environ)
		env["CUDA_VISIBLE_DEVICES"] = ""          # detach from the (possibly busy) GPU
		env["MINION_CPU_WORKER"] = "1"
		env["CPU_WORKER_NCTX"] = str(n_ctx)
		worker = [sys.executable, os.path.abspath(__file__), "--serve-cpu", "--port", str(CPU_WORKER_PORT)]
		if shutil.which("systemd-run"):
			cmd = ["systemd-run", "--user", "--scope", f"--unit={unit}",
				"-p", f"MemoryMax={shield}G", "--"] + worker
			self.worker = subprocess.Popen(cmd, env=env)
		else:
			# No systemd: still isolate the process group so we can kill it cleanly.
			self.worker = subprocess.Popen(worker, env=env, start_new_session=True)
		self.worker_port = CPU_WORKER_PORT
		self._await_worker_health()
		self.mode = "cpu"
		self.n_ctx = n_ctx
		logger.warning(f"CPU worker ready on 127.0.0.1:{self.worker_port} (pid={self.worker.pid}).")

	def _await_worker_health(self, timeout=180):
		import urllib.request
		deadline = time.time() + timeout
		url = f"http://127.0.0.1:{self.worker_port}/health"
		last_err = None
		while time.time() < deadline:
			if self.worker.poll() is not None:
				raise RuntimeError(f"CPU worker exited early (code {self.worker.returncode})")
			try:
				with urllib.request.urlopen(url, timeout=2) as r:
					if r.status == 200:
						return
			except Exception as e:
				last_err = e
				time.sleep(1)
		raise RuntimeError(f"CPU worker did not become healthy in {timeout}s (last: {last_err})")

	def unload_under_lock(self):
		if self.model is not None:
			logger.info(f"Unloading in-process model {MODEL_BASENAME} from VRAM/RAM...")
			self.model = None
			gc.collect()
		if self.worker is not None:
			logger.info(f"Stopping CPU worker (pid={self.worker.pid})...")
			unit = _cpu_worker_unit()
			if shutil.which("systemctl"):
				subprocess.run(["systemctl", "--user", "stop", f"{unit}.scope"],
					stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			try:
				self.worker.terminate()
				self.worker.wait(timeout=10)
			except Exception:
				try:
					os.killpg(os.getpgid(self.worker.pid), signal.SIGKILL)
				except Exception:
					pass
			self.worker = None
			self.worker_port = None
		self.mode = None
		self.n_ctx = None
		logger.info("Backend released.")

	async def check_idle(self):
		async with self.lock:
			if self.mode is not None:
				elapsed = time.time() - self.last_active
				timeout = DEFAULT_LOW_TIMEOUT if self.last_priority == "low" else DEFAULT_HIGH_TIMEOUT
				if elapsed > timeout:
					logger.info(f"Model idle timeout reached ({elapsed:.0f}s > {timeout}s, priority: {self.last_priority}). Auto-unloading...")
					self.unload_under_lock()

manager = ModelManager()


def _proxy_to_worker(port: int, body: Dict[str, Any]) -> Dict[str, Any]:
	"""Forward a chat request to the CPU worker (non-streamed) and return its JSON."""
	import urllib.request
	payload = dict(body)
	payload["stream"] = False
	data = json.dumps(payload).encode("utf-8")
	req = urllib.request.Request(
		f"http://127.0.0.1:{port}/v1/chat/completions",
		data=data,
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	with urllib.request.urlopen(req, timeout=600) as r:
		return json.loads(r.read().decode("utf-8"))


@app.on_event("startup")
async def startup_event():
	# The CPU worker is supervised by the parent; it does not run its own reaper.
	if not IS_CPU_WORKER:
		async def reaper():
			while True:
				await asyncio.sleep(5)
				await manager.check_idle()
		asyncio.create_task(reaper())
	role = "CPU worker" if IS_CPU_WORKER else "supervisor"
	logger.info(f"Dynamic model server initialized for profile '{PROFILE_NAME}' ({role}).")

@app.get("/health")
async def health():
	if not os.path.exists(MODEL_PATH) and not HF_REPO_ID:
		logger.error(f"Health check failed: Model file not found at {MODEL_PATH} and no hf_model_repo_id configured.")
		return JSONResponse(
			status_code=503,
			content={"status": "error", "reason": f"Model file not found at {MODEL_PATH} and no Hugging Face repository configured."}
		)
	return {"status": "ok"}

@app.get("/v1/models")
async def models():
	return {
		"object": "list",
		"data": [
			{
				"id": MODEL_BASENAME,
				"object": "model",
				"created": int(time.time()),
				"owned_by": "openai"
			}
		]
	}

@app.post("/unload")
@app.post("/v1/unload")
async def unload_endpoint():
	async with manager.lock:
		manager.unload_under_lock()
	return {"status": "unloaded"}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
	body = await request.json()
	messages = body.get("messages", [])
	stream = body.get("stream", False)
	active_chat_format = _resolve_chat_format(body)
	prefs = body.get("device_fallback")

	priority_header = request.headers.get("X-Task-Priority", "").lower()
	priority_body = body.get("priority", "").lower()
	is_low_priority = (priority_header == "low") or (priority_body == "low")

	loop = asyncio.get_running_loop()

	# Body-only keys that must not reach Llama.create_chat_completion.
	strip = ("model", "messages", "stream", "priority", "chat_format", "device_fallback")

	if stream and not IS_CPU_WORKER:
		async def stream_generator():
			async with manager.lock:
				manager.last_priority = "low" if is_low_priority else "high"
				try:
					await manager.ensure_backend_under_lock(prefs)
				except BackendUnavailable as e:
					yield f"data: {json.dumps({'error': str(e)})}\n\n"
					yield "data: [DONE]\n\n"
					return

				# CPU worker path: no streaming — emit one non-streamed chunk.
				if manager.mode == "cpu":
					result = await loop.run_in_executor(None, lambda: _proxy_to_worker(manager.worker_port, body))
					manager.last_active = time.time()
					yield f"data: {json.dumps(result)}\n\n"
					yield "data: [DONE]\n\n"
					return

				model = manager.model
				model.chat_format = active_chat_format

				def get_iterator():
					return model.create_chat_completion(
						messages=messages,
						stream=True,
						**kwargs
					)

				iterator = await loop.run_in_executor(None, get_iterator)

				try:
					while True:
						def get_next():
							try:
								return next(iterator)
							except StopIteration:
								return None

						chunk = await loop.run_in_executor(None, get_next)
						if chunk is None:
							break

						manager.last_active = time.time()
						yield f"data: {json.dumps(chunk)}\n\n"

					yield "data: [DONE]\n\n"
				except Exception as e:
					logger.error(f"Error in stream generation: {e}")
					yield f"data: {json.dumps({'error': str(e)})}\n\n"
				finally:
					manager.last_active = time.time()

		# Strip parameters that Llama.create_chat_completion accepts
		kwargs = {
			k: v for k, v in body.items()
			if k not in strip
		}
		return StreamingResponse(stream_generator(), media_type="text/event-stream")
	else:
		async with manager.lock:
			manager.last_priority = "low" if is_low_priority else "high"
			try:
				await manager.ensure_backend_under_lock(prefs)
			except BackendUnavailable as e:
				return JSONResponse(status_code=503, content={"error": str(e)})

			# Parent in CPU mode proxies to the isolated worker.
			if manager.mode == "cpu" and not IS_CPU_WORKER:
				result = await loop.run_in_executor(None, lambda: _proxy_to_worker(manager.worker_port, body))
				manager.last_active = time.time()
				return JSONResponse(content=result)

			model = manager.model
			model.chat_format = active_chat_format

			kwargs = {
				k: v for k, v in body.items()
				if k not in strip
			}

			def run_completion():
				return model.create_chat_completion(
					messages=messages,
					stream=False,
					**kwargs
				)

			response = await loop.run_in_executor(None, run_completion)
			manager.last_active = time.time()
			return JSONResponse(content=response)

def main():
	from red_pill.core.paths import get_daemon_dir

	parser = argparse.ArgumentParser()
	parser.add_argument("--serve-cpu", action="store_true", help="Run as an isolated CPU worker (CUDA detached by caller env).")
	parser.add_argument("--port", type=int, default=None)
	args, _ = parser.parse_known_args()

	# CPU worker: TCP only, single port, in-process CPU model.
	if args.serve_cpu or IS_CPU_WORKER:
		port = args.port or CPU_WORKER_PORT
		logger.info(f"Starting CPU worker on 127.0.0.1:{port} (CUDA_VISIBLE_DEVICES={os.getenv('CUDA_VISIBLE_DEVICES')!r})")
		uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
		return

	tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	tcp_sock.bind(("127.0.0.1", 8760))
	tcp_sock.listen()

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
	<key>EnvironmentVariables</key>
	<dict>
		<key>MINION_PROFILE</key>
		<string>granite_8b</string>
	</dict>
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
# Distiller profile served by the background daemon. Overrides run_dual_bind's
# "samantha" default. granite_8b is the AD-022 primary; hermes_8b is the fallback.
Environment=MINION_PROFILE=granite_8b
ExecStart=/bin/bash _PERSISTENT_DIR_/start.sh
Restart=always
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=yes
PrivateTmp=yes
# journald rotates automatically; append: files grow unbounded.
StandardOutput=journal
StandardError=journal

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
