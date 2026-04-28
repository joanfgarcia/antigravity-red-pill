import os
import subprocess
import time

MODEL_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf")
RUNNER_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/bin/llama-cli")

TEST_CASES = [
	{
		"name": "JSON Extraction",
		"prompt": "User: Extract the name and age from this text: 'My name is Alice and I am 25 years old.' Respond only in JSON format.\nAssistant:",
		"expected_substring": "Alice",
	},
	{
		"name": "Logic Puzzle",
		"prompt": "User: If I have 3 apples and you give me 2 more, how many apples do I have?\nAssistant:",
		"expected_substring": "5",
	},
	{
		"name": "System Command",
		"prompt": "User: What is the linux command to list files in the current directory?\nAssistant:",
		"expected_substring": "ls",
	},
]


def run_inference(prompt):
	cmd = [RUNNER_PATH, "-m", MODEL_PATH, "-p", prompt, "-n", "64", "-c", "512", "--temp", "0.1"]
	start_time = time.time()
	# Capturing stderr too because llama-cli often prints results mixed with logs
	result = subprocess.run(cmd, capture_output=True, text=True)
	end_time = time.time()

	# Simple heuristic to find content after the prompt
	full_output = result.stdout + result.stderr
	if "Assistant:" in full_output:
		output = full_output.split("Assistant:")[-1].strip()
	else:
		# Fallback: take the last part of the output
		output = full_output.strip().split("\n")[-1]

	return output, end_time - start_time


def validate():
	print("--- Starting BitNet Capacity Validation ---")
	for case in TEST_CASES:
		print(f"Testing {case['name']}...")
		output, duration = run_inference(case["prompt"])
		success = case["expected_substring"].lower() in output.lower()
		status = "PASSED" if success else "FAILED"

		print(f"[{status}] Time: {duration:.2f}s")
		print(f"Output: {output}\n")


if __name__ == "__main__":
	validate()
