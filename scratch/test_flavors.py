import json
import os
import signal
import subprocess
import time
from datetime import datetime

PROJECT_ROOT = os.getcwd()
BITNET_DIR = os.path.join(PROJECT_ROOT, "3rdparty/BitNet-1.58b")
MODEL_PATH = os.path.join(PROJECT_ROOT, "storage/models/falcon3-10b-instruct-1.58bit-V2.gguf")
API_URL = "http://127.0.0.1:8080/completion"
HEALTH_URL = "http://127.0.0.1:8080/health"

FLAVORS = {
	"CUDA":   {"dir": "build_cuda", "ngl": 35},
	"ROCm":   {"dir": "build_rocm", "ngl": 35},
	"NPU":    {"dir": "build_npu",  "ngl": 0},
}

QUERIES = [
	{"id": "Logic", "prompt": "Si tengo 5 manzanas y te doy 2, ¿cuántas manzanas tienes tú?"},
]

def wait_for_server(timeout=60):
	start = time.time()
	while time.time() - start < timeout:
		try:
			res = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", HEALTH_URL], capture_output=True, text=True)
			if res.stdout.strip() == "200":
				return True
		except Exception:
			pass
		time.sleep(1)
	return False

def run_flavor_bench(flavor_name, config):
	print(f"\n>>> TESTING: {flavor_name} <<<")
	build_dir = os.path.join(BITNET_DIR, config["dir"])
	server_bin = os.path.join(build_dir, "bin", "llama-server")

	if not os.path.exists(server_bin):
		print(f"ERROR: Binary not found: {server_bin}")
		return None

	env = os.environ.copy()
	if flavor_name == "CUDA":
		env["GGML_BITNET_FORCE_AXON"] = "CUDA"
	elif flavor_name == "ROCm":
		env["HSA_OVERRIDE_GFX_VERSION"] = "11.0.0"

	libs = [
		os.path.join(build_dir, "3rdparty/llama.cpp/src"),
		os.path.join(build_dir, "3rdparty/llama.cpp/ggml/src"),
	]
	if flavor_name == "ROCm":
		libs.insert(0, "/opt/rocm-6.4.1/lib")
	env["LD_LIBRARY_PATH"] = ":".join(libs) + ":" + env.get("LD_LIBRARY_PATH", "")

	cmd = [
		server_bin,
		"-m", MODEL_PATH,
		"-ngl", str(config["ngl"]),
		"-c", "2048",
		"--port", "8080",
		"--log-disable"
	]

	try:
		server_proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
		if not wait_for_server():
			print(f"ERROR: Server {flavor_name} timed out.")
			os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
			return None

		results = []
		for q in QUERIES:
			payload = {
				"prompt": f"<|im_start|>user\n{q['prompt']}<|im_end|>\n<|im_start|>assistant\n",
				"n_predict": 128,
				"temperature": 0.0,
				"stop": ["<|im_end|>"]
			}
			q_start = time.time()
			res = subprocess.run(["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(payload), API_URL], capture_output=True, text=True)
			q_duration = time.time() - q_start
			
			if res.returncode == 0:
				data = json.loads(res.stdout)
				tps = data.get("tokens_predicted", 0) / q_duration
				print(f"  {q['id']}: {tps:.2f} t/s | Response: {data.get('content', '').strip()[:50]}...")
				results.append({"id": q["id"], "tps": tps})

		os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
		server_proc.wait()
		return results
	except Exception as e:
		print(f"ERROR during {flavor_name}: {e}")
		return None

if __name__ == "__main__":
	for name, config in FLAVORS.items():
		run_flavor_bench(name, config)
