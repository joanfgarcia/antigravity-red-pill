import json
import os
import subprocess

MODEL_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/models/2B-4T/ggml-model-i2_s.gguf")
RUNNER_PATH = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build/bin/llama-cli")
GRAMMAR_PATH = os.path.join(os.getcwd(), "src/red_pill/inference/bitnet/json.gbnf")


def run_grammar_inference(prompt):
	cmd = [RUNNER_PATH, "-m", MODEL_PATH, "-p", prompt, "-n", "128", "-c", "512", "--temp", "0.1", "--grammar-file", GRAMMAR_PATH]
	result = subprocess.run(cmd, capture_output=True, text=True)
	full_output = result.stdout + result.stderr
	# With grammar, it usually starts with {
	if "{" in full_output:
		json_part = "{" + full_output.split("{", 1)[1].split("}", 1)[0] + "}"
		return json_part
	return full_output.strip()


def test_enhanced_trust():
	print("--- Testing BitNet + GBNF Grammar ---")
	prompt = "User: Generate a task with id 101, title 'Verify Swarm', and done true. Output JSON only.\nAssistant:"
	output = run_grammar_inference(prompt)
	print(f"Grammar Output: {output}")
	try:
		data = json.loads(output)
		print("[PASSED] JSON is valid!")
		print(f"Content: {data}")
		return True
	except Exception:
		print("[FAILED] Even with grammar, JSON parsing failed.")
		return False


if __name__ == "__main__":
	test_enhanced_trust()
