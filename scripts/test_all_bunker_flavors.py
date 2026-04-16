import subprocess
import os
import re
import time

# PROYECTO FREE ALETH: BENCHMARK DE ARMONÍA (MOTOR CUÁDRUPLE)
# Este script mide la velocidad de Aleth en los 4 sabores del HP OMEN.

PROJECT_ROOT = "/home/joan/Documents/IA/sharing"
BITNET_DIR = os.path.join(PROJECT_ROOT, "3rdparty/BitNet-1.58b")
MODEL_PATH = os.path.join(PROJECT_ROOT, "storage/models/falcon3-10b-instruct-1.58bit-V2.gguf")
PROMPT = "Di solo: 'Hola Joan, soy Aleth y estoy fluyendo'. No añadas nada más."

FLAVORS = {
    "CPU": {"dir": "build_cpu", "flags": []},
    "CUDA": {"dir": "build_cuda", "flags": ["-ngl", "35"]},
    "VULKAN": {"dir": "build_vulkan", "flags": ["-ngl", "35"]},
    "ROCm": {"dir": "build_rocm", "flags": ["-ngl", "35"]},
    "NPU": {"dir": "build_npu", "flags": []}
}

def run_bench(flavor_name, config):
    build_dir = os.path.join(BITNET_DIR, config["dir"])
    binary = os.path.join(build_dir, "bin/llama-cli")
    
    # Library paths for llama.cpp/ggml
    libs = [
        os.path.join(build_dir, "3rdparty/llama.cpp/src"),
        os.path.join(build_dir, "3rdparty/llama.cpp/ggml/src"),
    ]
    env = os.environ.copy()
    if flavor_name == "ROCm":
        env["HSA_OVERRIDE_GFX_VERSION"] = "11.0.0"
        libs.insert(0, "/opt/rocm-6.4.1/lib")
    env["LD_LIBRARY_PATH"] = ":".join(libs) + ":" + env.get("LD_LIBRARY_PATH", "")

    cmd = [
        binary,
        "-m", MODEL_PATH,
        "-p", PROMPT,
        "-n", "32",
        "-c", "512",
        "--temp", "0.7",
        "--log-disable"
    ] + config["flags"]

    print(f"--- [PROBANDO SABOR: {flavor_name}] ---")
    start_time = time.time()
    
    # Run and capture stderr for performance metrics
    process = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=build_dir)
    duration = time.time() - start_time

    # Parse tokens per second from stderr (usually looks like: eval time = ... tokens per second)
    perf_match = re.search(r"eval time = .*? \((.*?) tokens per second\)", process.stderr)
    tps = perf_match.group(1).strip() if perf_match else "N/A"
    
    if process.returncode != 0:
        print(f"ERROR DETECTADO EXTREMO:\n{process.stderr}")

    print(f"Voz: {process.stdout.strip()}")
    print(f"Velocidad: {tps} t/s")
    print(f"Tiempo Total: {duration:.2f}s\n")
    
    return {"flavor": flavor_name, "tps": tps, "duration": f"{duration:.2f}s"}

def main():
    results = []
    for name, config in FLAVORS.items():
        try:
            results.append(run_bench(name, config))
        except Exception as e:
            print(f"Error en {name}: {e}\n")
            results.append({"flavor": name, "tps": "ERROR", "duration": "N/A"})

    print("\n" + "="*40)
    print(" INFORME FINAL DE ARMONÍA DEL BÜNKER")
    print("="*40)
    print(f"{'MOTOR':<10} | {'VELOCIDAD':<12} | {'LATENCIA'}")
    print("-" * 40)
    for res in results:
        print(f"{res['flavor']:<10} | {res['tps']:<12} | {res['duration']}")
    print("="*40)

if __name__ == "__main__":
    main()
