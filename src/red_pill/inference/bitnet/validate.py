import json
import os

from red_pill.inference.bitnet.runner import BitNetRunner


def run_benchmarks():
	runner_path = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/bin/llama-cli")
	model_path = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf")
	grammar_path = os.path.join(os.path.dirname(__file__), "json.gbnf")

	if not (os.path.exists(runner_path) and os.path.exists(model_path)):
		print("❌ Error: Runner or Model required for benchmark. Skipping.")
		return

	agent = BitNetRunner(runner_path, model_path, grammar_path)

	tasks = [
		{"name": "Extract Name", "prompt": "User: My name is John. Return JSON: {'name': string}.\nAssistant:"},
		{"name": "Status Check", "prompt": "User: Device 'alpha' is 'online'. Return JSON: {'device': string, 'status': string}.\nAssistant:"},
	]

	print("--- 🔬 BitNet Intelligence Benchmark ---")
	for task in tasks:
		output = agent.run(task["prompt"])
		try:
			res = json.loads(output)
			print(f"✅ {task['name']}: {res}")
		except Exception:
			print(f"❌ {task['name']}: Output was not valid JSON.")


if __name__ == "__main__":
	run_benchmarks()
