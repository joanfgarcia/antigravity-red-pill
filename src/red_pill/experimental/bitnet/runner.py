import os
import subprocess


class BitNetRunner:
	def __init__(self, runner_path, model_path, grammar_path=None):
		self.runner_path = runner_path
		self.model_path = model_path
		self.grammar_path = grammar_path

	def run(self, prompt, max_tokens=128, temp=0.1):
		cmd = [self.runner_path, "-m", self.model_path, "-p", prompt, "-n", str(max_tokens), "--temp", str(temp)]
		if self.grammar_path:
			cmd.extend(["--grammar-file", self.grammar_path])

		result = subprocess.run(cmd, capture_output=True, text=True)
		full_output = result.stdout + result.stderr

		# Simple parsing for Assistant responses
		if "Assistant:" in full_output:
			return full_output.split("Assistant:")[-1].strip()
		return full_output.strip().split("\n")[-1]


if __name__ == "__main__":
	# Test execution
	RUNNER = "/home/joan/Documents/IA/experimental/BitNet/build/bin/llama-cli"
	MODEL = "/home/joan/Documents/IA/experimental/BitNet/models/2B-4T/ggml-model-i2_s.gguf"

	if os.path.exists(RUNNER) and os.path.exists(MODEL):
		agent = BitNetRunner(RUNNER, MODEL)
		print("Iniciando prueba rápida de agente...")
		print(agent.run("User: Identifícate.\nAssistant:"))
	else:
		print("Error: Runner o Modelo no encontrados. Consulta el README.md")
