import os
import subprocess
import time

MODELS_DIR = "/home/joan/Documents/IA/sharing/models/gguf"
MODELS = ["Falcon3-3B-Instruct-Heretic_Q4_K_M.gguf", "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf", "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"]

LLAMA_CLI = "/home/joan/Documents/IA/sharing/3rdparty/llama_official/build/bin/llama-cli"

PROMPTS = {
	"LOGIC_MATH": "I have 5 apples. I give 2 to you. Then I buy 3 more. How many apples do I have now?",
	"CODE_GENERATION": "Write a Python class for a Doubly Linked List with insert and delete methods. Only output code.",
	"CODE_DEBUGGING": "Find the bug in this Python code: 'def is_even(n):\n  if n % 2 = 0:\n    return True\n  return False'. Explain it briefly.",
	"SUMMARIZATION": "Summarize the history of the Apollo 11 moon landing in exactly 3 bullet points.",
	"DATA_EXTRACTION": "Extract the transactions into CSV format (Date, Name, Amount): On 2023-10-01, John bought a coffee for $5. On 2023-10-03, Mary paid $20 for lunch.",
	"TRANSLATION_IDIOM": "Translate this English idiom to Spanish and explain its meaning: 'It is raining cats and dogs'.",
	"INSTRUCTION_FOLLOWING": "Write a short poem about a cat. You must NOT use the letter 'e' anywhere in your response.",
}


def generate_response(model_path, prompt, max_tokens=256):
	chat_prompt = f"<|user|>\n{prompt}\n<|assistant|>\n"
	cmd = [
		"systemd-run",
		"--user",
		"--scope",
		"-p",
		"MemoryMax=10G",
		LLAMA_CLI,
		"-m",
		model_path,
		"-p",
		chat_prompt,
		"-n",
		str(max_tokens),
		"-c",
		"2048",  # Volvemos a 2k para ser conservadores
		"-ngl",
		"99",  # Full GPU
		"--temp",
		"0.1",
	]

	# Limpiamos LD_LIBRARY_PATH para evitar conflictos de ABI con el compilado antiguo de BitNet
	env = os.environ.copy()
	if "LD_LIBRARY_PATH" in env:
		# Quitamos la ruta de ollama local y bitnet para dejar limpio a Vulkan
		paths = env["LD_LIBRARY_PATH"].split(":")
		clean_paths = [p for p in paths if "BitNet" not in p and "ollama" not in p]
		env["LD_LIBRARY_PATH"] = ":".join(clean_paths)

	try:
		# Aumentamos el timeout a 20 minutos porque la compilación JIT de PTX a Blackwell puede ser masiva
		result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, env=env)
		output = result.stdout

		if "<|assistant|>" in output:
			return output.split("<|assistant|>")[-1].strip()
		elif "Assistant:" in output:
			return output.split("Assistant:")[-1].strip()

		lines = [line.strip() for line in output.split("\n") if line.strip()]
		return lines[-1] if lines else ""
	except subprocess.TimeoutExpired:
		return "Error: Vulkan shader compilation timed out or model hung (300s limit)."
	except Exception as e:
		return f"Error: {str(e)}"


def main():
	print("=" * 50, flush=True)
	print("🚀 INICIANDO LA ARENA SOBERANA (GGUF BENCHMARK - VULKAN)", flush=True)
	print("=" * 50, flush=True)

	for model_name in MODELS:
		model_path = os.path.join(MODELS_DIR, model_name)
		if not os.path.exists(model_path):
			print(f"\n⚠️ MODELO NO ENCONTRADO: {model_name}", flush=True)
			continue

		print(f"\n\n{'=' * 50}", flush=True)
		print(f"🥊 EVALUANDO MODELO: {model_name}", flush=True)
		print(f"{'=' * 50}", flush=True)

		for discipline, prompt in PROMPTS.items():
			print(f"\n--- 🧠 DISCIPLINA: {discipline} ---", flush=True)
			print(f"Prompt: {prompt}", flush=True)

			start_time = time.time()
			response = generate_response(model_path, prompt)
			duration = time.time() - start_time

			print(f"⏱️ Tiempo: {duration:.2f}s", flush=True)
			print(f"🤖 Respuesta:\n{response}\n", flush=True)
			print("-" * 40, flush=True)


if __name__ == "__main__":
	main()
