import json
import logging
import os
import time
import sys

# Ensure src is in PYTHONPATH
sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.core.providers import BitNetInferenceProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_bitnet_cuda")

def test():
	runner_bin = os.path.join(os.getcwd(), "3rdparty/BitNet-1.58b/build_cuda/bin/llama-cli")
	model_path = os.path.join(os.getcwd(), "storage/models/falcon3-10b-instruct-1.58bit-V2.gguf")
	
	if not os.path.exists(runner_bin):
		logger.error(f"❌ CUDA Runner missing: {runner_bin}")
		return

	logger.info("🚀 Starting BitNet CUDA Test...")
	provider = BitNetInferenceProvider(
		runner_path=runner_bin, 
		model_path=model_path
	)

	prompt = "User: Explain the theory of relativity in one sentence.\nAssistant:"
	logger.info(f"Running Prompt: {prompt}")

	# Set env vars for CUDA
	os.environ["GGML_BITNET_FORCE_AXON"] = "CUDA"
	
	start_time = time.time()
	# Use ngl=35 for full GPU offload
	response = provider.generate(prompt, max_tokens=128, ngl=35)
	duration = time.time() - start_time

	logger.info(f"⏱️  Duration: {duration:.2f}s")
	logger.info(f"🤖 Response: {response}")

if __name__ == "__main__":
	test()
