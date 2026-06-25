import argparse
import asyncio
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Dict

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

# Adjust import paths relying on IA_DIR structure
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(os.path.dirname(current_dir))
if src_dir not in sys.path:
	sys.path.insert(0, src_dir)

from red_pill.config import get_config  # noqa: E402
from red_pill.core.model_registry import ModelRegistry  # noqa: E402
from red_pill.core.paths import resolve_llama_binary  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [HYPERVISOR] %(message)s")
logger = logging.getLogger(__name__)

cfg = get_config()


class ActiveModel:
	def __init__(self, profile_name: str, profile: dict, ephemeral_port: int, process: subprocess.Popen):
		self.profile_name = profile_name
		self.profile = profile
		self.ephemeral_port = ephemeral_port
		self.process = process
		self.last_used = time.time()


class HypervisorManager:
	def __init__(self, ttl_seconds: int = 300):
		self.ttl_seconds = ttl_seconds
		self.active_models: Dict[str, ActiveModel] = {}
		self.lock = asyncio.Lock()
		self.http_client = httpx.AsyncClient(timeout=None)

	def get_free_port(self) -> int:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.bind(("", 0))
			return int(s.getsockname()[1])

	async def ensure_model(self, requested_capability: str) -> ActiveModel:
		profile_name, profile = ModelRegistry.get_profile_by_capability(requested_capability)
		if not profile_name:
			raise ValueError(f"No profile found for capability: {requested_capability}")

		async with self.lock:
			if profile_name in self.active_models:
				active = self.active_models[profile_name]
				active.last_used = time.time()
				if active.process.poll() is None:
					return active
				else:
					logger.warning(f"Model {profile_name} crashed. Restarting...")
					del self.active_models[profile_name]

			logger.info(f"Booting model: {profile_name} (Capability: {requested_capability})")
			ephemeral_port = self.get_free_port()

			# Resolve binary types
			model_path = os.path.join(cfg.APP_ROOT, profile.get("model_path", ""))
			binary_type = profile.get("binary_type", "gguf")

			# Build command based on OS/binary type logic
			os_name = os.uname().sysname
			if os_name == "Darwin" and binary_type == "gguf":
				# Assuming mlx_lm is installed
				cmd = ["mlx_lm.server", "--model", model_path, "--port", str(ephemeral_port)]
			else:
				# Assume llama-server for both BitNet custom and GGUF standard
				llama_path = str(resolve_llama_binary())
				ctx = str(profile.get("context_size", 2048))
				ngl = str(profile.get("n_gpu_layers", 999))
				cmd = [llama_path, "-m", model_path, "--port", str(ephemeral_port), "-c", ctx, "-ngl", ngl]

			logger.info(f"Exec: {' '.join(cmd)}")
			process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

			active_model = ActiveModel(profile_name, profile, ephemeral_port, process)
			self.active_models[profile_name] = active_model

			# Wait for /health to return status: ok (max 60s)
			for _ in range(120):
				try:
					resp = await self.http_client.get(f"http://127.0.0.1:{ephemeral_port}/health")
					if resp.status_code == 200 and resp.json().get("status") == "ok":
						break
				except Exception:
					pass
				await asyncio.sleep(0.5)

			logger.info(f"Model {profile_name} stabilized on port {ephemeral_port}")
			return active_model

	async def garbage_collector(self):
		while True:
			await asyncio.sleep(60)
			now = time.time()
			async with self.lock:
				to_remove = []
				for name, active in self.active_models.items():
					if now - active.last_used > self.ttl_seconds:
						logger.info(f"VRAM Garbage Collection: Unloading idle model {name} (TTL > {self.ttl_seconds}s)")
						active.process.terminate()
						try:
							active.process.wait(timeout=5)
						except subprocess.TimeoutExpired:
							logger.warning(f"Model {name} zombie detected, sending SIGKILL.")
							active.process.kill()
						to_remove.append(name)
				for name in to_remove:
					del self.active_models[name]

	async def proxy_request(self, request: Request, active_model: ActiveModel):
		url = f"http://127.0.0.1:{active_model.ephemeral_port}{request.url.path}"
		body = await request.body()
		req = self.http_client.build_request(
			method=request.method, url=url, headers={k: v for k, v in request.headers.items() if k.lower() != "host"}, content=body
		)
		# Proxy stream
		response = await self.http_client.send(req, stream=True)

		async def stream_generator():
			async for chunk in response.aiter_raw():
				yield chunk

		return StreamingResponse(
			stream_generator(),
			status_code=response.status_code,
			headers={k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "transfer-encoding")},
		)


app = FastAPI(title="Cognitive Hypervisor")
manager = HypervisorManager()


@app.on_event("startup")
async def startup_event():
	asyncio.create_task(manager.garbage_collector())


@app.get("/health")
async def health_check():
	return {"status": "ok", "active_models": list(manager.active_models.keys())}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
	# Parse capability from payload if possible
	body = await request.body()
	requested_capability = "logic"  # fallback fast/base model
	try:
		import json

		data = json.loads(body.decode())
		# If the request targets a specific model by name, use it. Some agents might send {"model": "deep"}
		if "model" in data:
			req_model = data["model"].lower()
			if req_model in ["samantha", "deep", "distillation"]:
				requested_capability = "distillation"
			else:
				requested_capability = "logic"
	except Exception:
		pass

	try:
		active_model = await manager.ensure_model(requested_capability)
		return await manager.proxy_request(request, active_model)
	except Exception as e:
		logger.error(f"Hypervisor Proxy Pipeline Error: {e}")
		from fastapi.responses import JSONResponse

		return JSONResponse(status_code=500, content={"error": str(e)})


def main():
	parser = argparse.ArgumentParser(description="Cognitive Hypervisor Daemon")
	parser.add_argument("--tcp-port", type=int, default=8760, help="TCP Fallback Port")
	args = parser.parse_args()

	uds_path = cfg.SIP_SOCKET_PATH
	if os.path.exists(uds_path):
		os.remove(uds_path)

	tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	tcp_sock.bind(("127.0.0.1", args.tcp_port))
	tcp_sock.listen()

	uds_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	uds_sock.bind(uds_path)
	uds_sock.listen()
	os.chmod(uds_path, 0o600)

	config = uvicorn.Config(app=app, log_level="info")
	server = uvicorn.Server(config=config)

	logger.info(f"Hypervisor Sub-Socket UDS Array active on {uds_path}")

	loop = asyncio.get_event_loop()
	loop.run_until_complete(server.serve(sockets=[tcp_sock, uds_sock]))


if __name__ == "__main__":
	main()
