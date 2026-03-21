import json
import logging
import os
import time

from red_pill.core.providers import BitNetInferenceProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_bitnet")


def validate():
	# 1. Configuration (Matching Enterprise Paths)
	runner_bin = "/home/joan/Documents/IA/experimental/BitNet/build/bin/llama-cli"
	model_path = "/home/joan/Documents/IA/experimental/BitNet/models/2B-4T/ggml-model-i2_s.gguf"
	grammar_path = os.path.join(os.getcwd(), "src/red_pill/experimental/bitnet/json.gbnf")

	if not os.path.exists(runner_bin) or not os.path.exists(model_path):
		logger.error("❌ BitNet Hardware/Model missing at configured paths.")
		print(f"Missing: {runner_bin if not os.path.exists(runner_bin) else model_path}")
		return

	logger.info("🚀 Starting BitNet Validation (Phase 2)...")
	provider = BitNetInferenceProvider(
		runner_path=runner_bin, model_path=model_path, grammar_path=grammar_path if os.path.exists(grammar_path) else None
	)

	# 2. Test Case: Identity
	prompt = "User: Who are you?\nAssistant:"
	logger.info(f"Running Prompt: {prompt}")

	start_time = time.time()
	response = provider.generate(prompt, max_tokens=64)
	duration = time.time() - start_time

	logger.info(f"⏱️  Duration: {duration:.2f}s")
	logger.info(f"🤖 Response: {response}")

	# 3. Test Case: JSON Extraction (if grammar exists)
	if os.path.exists(grammar_path):
		logger.info("🔬 Testing JSON Grammar Enforcement...")
		json_prompt = "User: Create a JSON object for a user named 'Aleth' with status 'active'.\nAssistant:"
		json_response = provider.generate(json_prompt, max_tokens=128)
		logger.info(f"📦 JSON Output: {json_response}")
		try:
			parsed = json.loads(json_response)
			logger.info(f"✅ JSON Parse Success: {parsed}")
		except:
			logger.warning("⚠️  JSON Grammar check failed or output was malformed.")

	logger.info("✨ Validation Complete.")


if __name__ == "__main__":
	validate()
