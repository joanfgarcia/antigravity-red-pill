import gc
import os

# 1. Fallback to basic extraction if llama_cpp is not available
try:
	from llama_cpp import Llama
	LLAMA_AVAILABLE = True
except ImportError:
	LLAMA_AVAILABLE = False

class EdgeCompressor:
	"""
	Local SLM logic for prompt compression.
	Only instantiated via the Minion if the user has a model downloaded.
	"""
	def __init__(self, model_path: str, n_gpu_layers: int = -1):
		self.model_path = model_path
		self.llm = None

		# Only load if python binding exists
		if LLAMA_AVAILABLE and model_path and os.path.exists(model_path):
			try:
				self.llm = Llama(
					model_path=model_path,
					n_ctx=4096,  
					n_gpu_layers=n_gpu_layers,
					verbose=False
				)
			except Exception as e:
				pass

	def compress(self, text: str) -> str:
		if not self.llm:
			return self._fallback_compress(text)

		try:
			system_prompt = (
				"You are a strict technical extractor. "
				"Extract ONLY the core instructions and technical requirements. "
				"Extreme brevity. Bullet points. Same language as user."
			)
			# ChatML format for Qwen
			prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"

			output = self.llm(
				prompt,
				max_tokens=256,
				stop=["<|im_end|>", "<|im_start|>", "</s>"],
				temperature=0.1,
				repeat_penalty=1.1
			)
			return output["choices"][0]["text"].strip()

		except Exception as e:
			print(f"Edge compression failed: {e}")
			return self._fallback_compress(text)
		finally:
			# Aggressive cleanup since this is a side-agent
			gc.collect()

	def _fallback_compress(self, text: str) -> str:
		import re
		clean_text = re.sub(r'^(hola|buenos\s+d[íi]as|oye|por\s+favor)[,\s]*', '', text, flags=re.IGNORECASE)
		clean_text = re.sub(r'[,\s]*(gracias|un\s+saludo|adi[óo]s)$', '', clean_text, flags=re.IGNORECASE)
		sentences = [s.strip() for s in re.split(r'[.!?\n]+', clean_text) if len(s.strip()) > 5]
		compressed_lines = []
		for s in sentences:
			fluff = [
				"necesito que", "me gustaría saber si", "podrías", "te importaría",
				"estoy intentando", "creo que", "básicamente lo que pasa es que"
			]
			for f in fluff:
				s = re.sub(fr'\b{f}\b', '', s, flags=re.IGNORECASE)
			s = s.strip()
			if s:
				compressed_lines.append(f"- {s.capitalize()}")
		synthesis = "\n".join(compressed_lines)
		return synthesis if synthesis else text.strip()
