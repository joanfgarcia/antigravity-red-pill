import json
import os
import subprocess

import pytest

MODEL_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf")
RUNNER_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/bin/llama-cli")


def run_raw_inference(prompt):
	cmd = [RUNNER_PATH, "-m", MODEL_PATH, "-p", prompt, "-n", "128", "-c", "512", "--temp", "0.1"]
	result = subprocess.run(cmd, capture_output=True, text=True)
	full_output = result.stdout + result.stderr
	if "Assistant:" in full_output:
		return full_output.split("Assistant:")[-1].strip()
	return full_output.strip().split("\n")[-1]


@pytest.mark.skipif(not os.path.exists(RUNNER_PATH), reason="BitNet-1.58b not installed")
def test_consistency():
	print("--- Test 1: Consistency (5 iterations) ---")
	prompt = "User: List the first 5 prime numbers.\nAssistant:"
	results = []
	for i in range(5):
		output = run_raw_inference(prompt)
		results.append(output)
		print(f"Iter {i + 1}: {output}")

	unique_count = len(set(results))
	print(f"Unique answers: {unique_count}/5")
	return unique_count == 1


@pytest.mark.skipif(not os.path.exists(RUNNER_PATH), reason="BitNet-1.58b not installed")
def test_schema_adherence():
	print("\n--- Test 2: Schema Adherence ---")
	prompt = "User: Generate a JSON object for a task with 'id' (int), 'title' (string), and 'done' (boolean). Only output the JSON.\nAssistant:"
	output = run_raw_inference(prompt)
	print(f"Output: {output}")
	try:
		data = json.loads(output)
		required = ["id", "title", "done"]
		missing = [f for f in required if f not in data]
		if not missing:
			print("[PASSED] Valid JSON and schema.")
			return True
		else:
			print(f"[FAILED] Missing fields: {missing}")
			return False
	except Exception:
		print("[FAILED] Invalid JSON format.")
		return False


if __name__ == "__main__":
	c_pass = test_consistency()
	s_pass = test_schema_adherence()

	print("\n--- Reliability Report ---")
	print(f"Deterministic Consistency: {'OK' if c_pass else 'VARIES'}")
	print(f"Schema Integrity: {'HIGH' if s_pass else 'LOW'}")
