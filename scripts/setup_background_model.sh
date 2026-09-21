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
"""Red Pill Dynamic Inference Proxy — SERVICIO DE GOBIERNO (RFC-HARNESS-002 v3).

Selector `(task, model, thinking, custom, experimental)` resuelto SIEMPRE bajo
el lock vía `model_runtime`; cambio de modelo sin reiniciar; chat handlers por
modo thinking (template nativo); `/status` con thinking_mode; fallup CPU→GPU;
worker CPU aislado; health liveness 200 incondicional.

Generado desde setup_background_model.sh (fuente de verdad). NO editar a mano.
"""
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [DUAL_BIND] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Red Pill Inference Governance Proxy")

from red_pill.core import model_runtime as mr
from red_pill.core.model_license import ModelLicenseError
from red_pill.core.model_registry import ModelRegistry
from red_pill.core.paths import resolve_model_path
from red_pill.core.vram_probe import VramProbe
from red_pill.inference.runtime import apply_chat_handler as _apply_chat_handler, register_thinking_handlers as _register_thinking_handlers

# Env del worker CPU (imposición del padre, RFC §10): el worker resuelve con el
# selector igual que el padre, pero su env lo fija el padre al spawnearlo.
CPU_WORKER_PORT = int(os.getenv("CPU_WORKER_PORT", "8761"))
IS_CPU_WORKER = os.getenv("MINION_CPU_WORKER") == "1"
FORCED_NCTX = int(os.getenv("CPU_WORKER_NCTX", "0")) or None
_CPU_BASE_GB = 9.0
_CPU_KV_MB_PER_TOKEN = 0.16

DEFAULT_HIGH_TIMEOUT = 300
DEFAULT_LOW_TIMEOUT = 10

# Chat handlers por modo thinking: única verdad en red_pill.inference.runtime
# (compartida con el front CLI del bake-off). Se importan arriba como
# _apply_chat_handler / _register_thinking_handlers.


class BackendUnavailable(RuntimeError):
	pass


class ModelManager:
	def __init__(self):
		self.model = None
		self.worker = None
		self.worker_port = None
		self.mode = None
		self.n_ctx = None
		self.current: Optional[mr.ResolvedModel] = None
		self.lock = asyncio.Lock()
		self.last_active = time.time()
		self.last_priority = "high"
		self._last_status_error: Optional[str] = None

	async def resolve_and_ensure(self, body: Dict[str, Any], prefs: Optional[List[str]] = None):
		"""Resuelve el selector y carga el modelo si difiere del actual (bajo lock)."""
		self.last_active = time.time()
		resolved = mr.resolve(body)
		if self.mode is not None and self.current and self._same_model(self.current, resolved):
			# Mismo modelo: solo aplicar chat handler/thinking de la request.
			self._apply_resolved(body, resolved)
			return resolved
		await self._switch_to(resolved, prefs)
		return resolved

	@staticmethod
	def _same_model(a: mr.ResolvedModel, b: mr.ResolvedModel) -> bool:
		return a.model_path == b.model_path and a.n_ctx == b.n_ctx and a.mode == b.mode

	def _apply_resolved(self, body: Dict[str, Any], resolved: mr.ResolvedModel) -> None:
		if self.model is not None:
			_apply_chat_handler(self.model, resolved, body)
		self.current = resolved

	async def _switch_to(self, resolved: mr.ResolvedModel, prefs: Optional[List[str]]):
		self.unload_under_lock()
		# Tras el unload la VRAM está libre: re-evaluar el tier (el resolve
		# inicial pudo calcularlo con el modelo anterior ocupando VRAM).
		if resolved.mode != "experimental":
			resolved = mr.refresh_hardware_tier(resolved)
		cascade = prefs or resolved.device_fallback or ["gpu", "cpu"]
		errors = []
		gpu_reserved = False
		try:
			from red_pill.core.gpu_reservation import GpuReservationManager
			gpu_reserved = GpuReservationManager.is_exclusive_active()
		except Exception as e:
			logger.warning(f"Error checking GPU reservation: {e}")
		for device in cascade:
			try:
				if device == "gpu":
					if gpu_reserved:
						errors.append("gpu: exclusive GPU reservation is active")
						continue
					if IS_CPU_WORKER:
						continue
					ngl = resolved.n_gpu_layers
					if ngl == 0:
						errors.append("gpu: insufficient free VRAM")
						continue
					self._load_in_process(resolved, resolved.n_ctx, ngl)
					return
				elif device == "cpu":
					self._start_cpu_worker(resolved)
					return
				elif device in ("igpu", "npu"):
					logger.warning(f"Device '{device}' not wired yet; skipping.")
					errors.append(f"{device}: not implemented")
					continue
				else:
					errors.append(f"{device}: unknown")
					continue
			except Exception as e:
				logger.error(f"Device '{device}' failed: {e!r}")
				errors.append(f"{device}: {e}")
				continue
		raise BackendUnavailable(f"No usable device in {cascade}: {errors}")

	def _load_in_process(self, resolved: mr.ResolvedModel, n_ctx: int, n_gpu_layers: int):
		where = "CPU worker" if IS_CPU_WORKER else "GPU/in-process"
		logger.info(f"Loading model ({where}): {resolved.profile_name} ({resolved.model_path.split('/')[-1]}) "
			f"GPU layers: {n_gpu_layers}, Context: {n_ctx}")
		if not os.path.exists(resolved.model_path):
			raise BackendUnavailable(f"model file not found: {resolved.model_path}")
		from llama_cpp import Llama
		self.model = Llama(
			model_path=resolved.model_path,
			chat_format=resolved.chat_format,
			n_ctx=n_ctx,
			n_gpu_layers=n_gpu_layers,
			verbose=False,
		)
		_register_thinking_handlers(self.model, resolved)
		self.mode = "cpu" if IS_CPU_WORKER else "gpu"
		self.n_ctx = n_ctx
		self.current = resolved
		mr.mark_load_verified(resolved.model_path)
		logger.info(f"Model {resolved.profile_name} successfully loaded ({where}).")

	def _start_cpu_worker(self, resolved: mr.ResolvedModel):
		n_ctx = resolved.cpu_n_ctx or resolved.n_ctx
		shield = math.ceil((_CPU_BASE_GB + (n_ctx * _CPU_KV_MB_PER_TOKEN) / 1024.0) * 1.15)
		logger.warning(f"GPU unavailable for {resolved.profile_name}: falling back to CPU (n_ctx={n_ctx}, shield={shield}G).")
		unit = f"redpill-cpu-worker-{CPU_WORKER_PORT}"
		if shutil.which("systemctl"):
			subprocess.run(["systemctl", "--user", "reset-failed", f"{unit}.scope"],
				stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		env = dict(os.environ)
		env["CUDA_VISIBLE_DEVICES"] = ""
		env["MINION_CPU_WORKER"] = "1"
		env["CPU_WORKER_NCTX"] = str(n_ctx)
		worker = [sys.executable, os.path.abspath(__file__), "--serve-cpu", "--port", str(CPU_WORKER_PORT)]
		if shutil.which("systemd-run"):
			cmd = ["systemd-run", "--user", "--scope", f"--unit={unit}", "-p", f"MemoryMax={shield}G", "--"] + worker
			self.worker = subprocess.Popen(cmd, env=env)
		else:
			self.worker = subprocess.Popen(worker, env=env, start_new_session=True)
		self.worker_port = CPU_WORKER_PORT
		self._await_worker_health()
		self.mode = "cpu"
		self.n_ctx = n_ctx
		self.current = resolved
		logger.warning(f"CPU worker ready on 127.0.0.1:{self.worker_port} (pid={self.worker.pid}).")

	def _await_worker_health(self, timeout=180):
		import urllib.request
		deadline = time.time() + timeout
		url = f"http://127.0.0.1:{self.worker_port}/health"
		while time.time() < deadline:
			if self.worker.poll() is not None:
				raise RuntimeError(f"CPU worker exited early (code {self.worker.returncode})")
			try:
				with urllib.request.urlopen(url, timeout=2) as r:
					if r.status == 200:
						return
			except Exception:
				time.sleep(1)
		raise RuntimeError(f"CPU worker did not become healthy in {timeout}s")

	def unload_under_lock(self):
		if self.model is not None:
			name = getattr(self.current, "profile_name", "?")
			logger.info(f"Unloading in-process model {name}...")
			self.model = None
			gc.collect()
		if self.worker is not None:
			unit = f"redpill-cpu-worker-{CPU_WORKER_PORT}"
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
		self.current = None
		logger.info("Backend released.")

	async def check_idle(self):
		async with self.lock:
			if self.mode is not None:
				elapsed = time.time() - self.last_active
				timeout = DEFAULT_LOW_TIMEOUT if self.last_priority == "low" else DEFAULT_HIGH_TIMEOUT
				if elapsed > timeout:
					logger.info(f"Idle timeout reached ({elapsed:.0f}s > {timeout}s, priority={self.last_priority}). Auto-unloading...")
					self.unload_under_lock()


manager = ModelManager()


def _proxy_to_worker(port: int, body: Dict[str, Any]) -> Dict[str, Any]:
	import urllib.request
	payload = dict(body)
	payload["stream"] = False
	data = json.dumps(payload).encode("utf-8")
	req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=data,
		headers={"Content-Type": "application/json"}, method="POST")
	with urllib.request.urlopen(req, timeout=600) as r:
		return json.loads(r.read().decode("utf-8"))


@app.on_event("startup")
async def startup_event():
	if not IS_CPU_WORKER:
		async def reaper():
			while True:
				await asyncio.sleep(5)
				await manager.check_idle()
		asyncio.create_task(reaper())
	role = "CPU worker" if IS_CPU_WORKER else "supervisor"
	logger.info(f"Inference governance server initialized ({role}).")


@app.get("/health")
async def health():
	# Liveness incondicional (RFC §9): nunca 503 durante un switch.
	return {"status": "ok"}


@app.get("/v1/models")
async def models():
	if manager.mode is None:
		eff = mr.effective_default()
		return {"object": "list", "data": [{
			"id": eff.profile_name or "",
			"object": "model", "created": int(time.time()), "owned_by": "openai",
			"loaded": False, "mode": None,
		}]}
	res = manager.current
	return {"object": "list", "data": [{
		"id": res.profile_name if res else "",
		"object": "model", "created": int(time.time()), "owned_by": "openai",
		"loaded": True, "mode": manager.mode,
		"context_length": manager.n_ctx,
	}]}


@app.get("/status")
async def status():
	res = manager.current
	return {
		"loaded_profile": res.profile_name if res else None,
		"loaded_model": os.path.basename(res.model_path) if res else None,
		"mode": manager.mode,
		"n_ctx": manager.n_ctx,
		"busy": manager.lock.locked(),
		"thinking_mode": res.thinking if res else None,
		"last_mode": res.last_mode if res else "none",
		"vram_free_mb": VramProbe.get_free_mb(),
		"effective_default": mr.effective_default().profile_name,
	}


@app.post("/unload")
@app.post("/v1/unload")
async def unload_endpoint():
	async with manager.lock:
		manager.unload_under_lock()
	return {"status": "unloaded"}


@app.post("/v1/tokenize")
async def tokenize_endpoint(request: Request):
	"""Cuenta tokens reales de un texto con el tokenizer del modelo CARGADO.

	RFC-HARNESS-002 §7 (v3, pendiente-final): útil para dimensionar los splits
	del refine/distill del pase Memento por TOKENS REALES en vez de chars (el
	ratio chars/token varía 1-4, ningún presupuesto fijo es seguro). Universal:
	todo GGUF lleva su tokenizer.

	Body: {"text": "..."} → {"count": N, "tokens": [...], "n_ctx": N}
	503 si no hay modelo cargado (el tokenizer vive en el modelo).
	"""
	body = await request.json()
	text = body.get("text", "")
	if not isinstance(text, str) or not text:
		return JSONResponse(status_code=400, content={"error": "body.text (string) es obligatorio"})

	async with manager.lock:
		if manager.model is None or manager.mode == "cpu":
			# El worker CPU tiene su propio modelo; si el padre no tiene el suyo
			# cargado, reenviar al worker si existe.
			if manager.mode == "cpu" and manager.worker_port:
				import urllib.request as _ur

				payload = json.dumps(body).encode("utf-8")
				req = _ur.Request(f"http://127.0.0.1:{manager.worker_port}/v1/tokenize", data=payload,
					headers={"Content-Type": "application/json"}, method="POST")
				with _ur.urlopen(req, timeout=30) as resp:
					return JSONResponse(content=json.loads(resp.read().decode()))
			return JSONResponse(status_code=503, content={"error": "no hay modelo cargado para tokenizar"})

		try:
			tokens = manager.model.tokenize(text.encode("utf-8"))
		except Exception as e:
			return JSONResponse(status_code=400, content={"error": f"tokenize falló: {e}"})
		manager.last_active = time.time()
		return {"count": len(tokens), "tokens": list(tokens), "n_ctx": manager.n_ctx}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
	body = await request.json()
	messages = body.get("messages", [])
	stream = body.get("stream", False)
	priority_header = request.headers.get("X-Task-Priority", "").lower()
	priority_body = body.get("priority", "").lower()
	is_low_priority = (priority_header == "low") or (priority_body == "low")
	loop = asyncio.get_running_loop()

	strip = ("model", "messages", "stream", "priority", "chat_format", "device_fallback",
	         "task", "thinking", "custom", "experimental")

	if stream and not IS_CPU_WORKER:
		async def stream_generator():
			async with manager.lock:
				manager.last_priority = "low" if is_low_priority else "high"
				try:
					await manager.resolve_and_ensure(body)
				except (BackendUnavailable, mr.ModelRuntimeError, ModelLicenseError) as e:
					yield f"data: {json.dumps({'error': str(e)})}\n\n"
					yield "data: [DONE]\n\n"
					return
				if manager.mode == "cpu":
					result = await loop.run_in_executor(None, lambda: _proxy_to_worker(manager.worker_port, body))
					manager.last_active = time.time()
					yield f"data: {json.dumps(result)}\n\n"
					yield "data: [DONE]\n\n"
					return
				model = manager.model
				_apply_chat_handler(model, manager.current, body)
				kwargs = {k: v for k, v in body.items() if k not in strip}

				def get_iterator():
					return model.create_chat_completion(messages=messages, stream=True, **kwargs)
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
					logger.error(f"Error in stream: {e}")
					yield f"data: {json.dumps({'error': str(e)})}\n\n"
				finally:
					manager.last_active = time.time()
		return StreamingResponse(stream_generator(), media_type="text/event-stream")

	async with manager.lock:
		manager.last_priority = "low" if is_low_priority else "high"
		try:
			await manager.resolve_and_ensure(body)
		except (BackendUnavailable, mr.ModelRuntimeError, ModelLicenseError) as e:
			return JSONResponse(status_code=400 if isinstance(e, (mr.ModelRuntimeError, ModelLicenseError)) else 503,
				content={"error": str(e)})

		if manager.mode == "cpu" and not IS_CPU_WORKER:
			result = await loop.run_in_executor(None, lambda: _proxy_to_worker(manager.worker_port, body))
			manager.last_active = time.time()
			return JSONResponse(content=result)

		model = manager.model
		_apply_chat_handler(model, manager.current, body)
		kwargs = {k: v for k, v in body.items() if k not in strip}

		def run_completion():
			return model.create_chat_completion(messages=messages, stream=False, **kwargs)
		response = await loop.run_in_executor(None, run_completion)
		manager.last_active = time.time()
		return JSONResponse(content=response)


def main():
	from red_pill.core.paths import get_daemon_dir
	parser = argparse.ArgumentParser()
	parser.add_argument("--serve-cpu", action="store_true", help="Run as an isolated CPU worker.")
	parser.add_argument("--port", type=int, default=None)
	args, _ = parser.parse_known_args()

	if args.serve_cpu or IS_CPU_WORKER:
		port = args.port or CPU_WORKER_PORT
		logger.info(f"Starting CPU worker on 127.0.0.1:{port}")
		uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
		return

	tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	tcp_sock.bind(("127.0.0.1", args.port or 8760))
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
		<key>MINION_DEFAULT_PROFILE</key>
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
Environment=MINION_DEFAULT_PROFILE=granite_8b
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
