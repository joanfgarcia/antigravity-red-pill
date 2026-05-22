import os
import subprocess


class BitNetRunner:
	"""
	Lightweight runner for BitNet 1.58-bit ternary models via llama-cli.
	Auto-detects CUDA build and sets LD_LIBRARY_PATH accordingly.
	"""

	DEFAULT_CTX = 4096
	MAX_CTX_CUDA = 16384  # Max for 8GB VRAM (RTX 5070 Laptop)
	MAX_CTX_CPU = 2048

	def __init__(self, runner_path, model_path, grammar_path=None, ngl=0, ctx_size=None):
		self.runner_path = runner_path
		self.model_path = model_path
		self.grammar_path = grammar_path
		self.ngl = ngl
		self.ctx_size = ctx_size or self.DEFAULT_CTX

	@classmethod
	def auto_detect(cls, workspace=None):
		"""Factory: auto-detect best available build (CUDA > CPU)."""
		workspace = workspace or os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
		bitnet_root = os.path.join(workspace, "sharing", "3rdparty", "BitNet-1.58b")
		model_path = os.path.join(bitnet_root, "models", "Falcon3-10B-Instruct-1.58bit", "ggml-model-i2_s.gguf")

		if not os.path.exists(model_path):
			return None

		# Prefer CUDA build
		cuda_runner = os.path.join(bitnet_root, "build_cuda", "bin", "llama-cli")
		if os.path.exists(cuda_runner):
			return cls(cuda_runner, model_path, ngl=99, ctx_size=cls.DEFAULT_CTX)

		# Fallback to CPU
		cpu_runner = os.path.join(bitnet_root, "build_cpu", "bin", "llama-cli")
		if os.path.exists(cpu_runner):
			return cls(cpu_runner, model_path, ngl=0, ctx_size=cls.MAX_CTX_CPU)

		# Generic build
		generic_runner = os.path.join(bitnet_root, "build", "bin", "llama-cli")
		if os.path.exists(generic_runner):
			return cls(generic_runner, model_path, ngl=0, ctx_size=cls.MAX_CTX_CPU)

		return None

	def _build_env(self):
		"""Set LD_LIBRARY_PATH based on build variant."""
		env = os.environ.copy()
		build_dir = os.path.dirname(os.path.dirname(self.runner_path))  # build_cuda/ or build/
		lib_path = os.path.join(build_dir, "3rdparty", "llama.cpp", "src")
		ggml_path = os.path.join(build_dir, "3rdparty", "llama.cpp", "ggml", "src")
		env["LD_LIBRARY_PATH"] = f"{lib_path}:{ggml_path}:" + env.get("LD_LIBRARY_PATH", "")
		return env

	def run(self, prompt, max_tokens=128, temp=0.1, ctx_size=None):
		ctx = ctx_size or self.ctx_size
		cmd = [
			self.runner_path, "-m", self.model_path,
			"-p", prompt,
			"-n", str(max_tokens),
			"--temp", str(temp),
			"-c", str(ctx),
			"-ngl", str(self.ngl),
		]
		if self.grammar_path:
			cmd.extend(["--grammar-file", self.grammar_path])

		try:
			result = subprocess.run(
				cmd, capture_output=True, text=True,
				timeout=120, env=self._build_env()
			)
			full_output = result.stdout + result.stderr

			# Parse assistant response
			if "<|assistant|>" in full_output:
				return full_output.split("<|assistant|>")[-1].split("[end of text]")[0].strip()
			if "Assistant:" in full_output:
				return full_output.split("Assistant:")[-1].split("[end of text]")[0].strip()
			if prompt in full_output:
				return full_output.split(prompt)[-1].split("[end of text]")[0].strip()
			return full_output.strip().split("\n")[-1]
		except subprocess.TimeoutExpired:
			return "Error: BitNet inference timed out."
		except Exception as e:
			return f"Error: BitNet subprocess failed: {e}"


if __name__ == "__main__":
	runner = BitNetRunner.auto_detect()
	if runner:
		print(f"Build: {runner.runner_path}")
		print(f"Model: {runner.model_path}")
		print(f"NGL: {runner.ngl}, CTX: {runner.ctx_size}")
		print("---")
		print(runner.run("What is the capital of France? Answer briefly.", max_tokens=50, temp=0.0))
	else:
		print("Error: No BitNet runner or model found. Check 3rdparty/BitNet-1.58b/")
