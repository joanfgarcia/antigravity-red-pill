import os
import sys

import numpy as np

try:
	from llama_cpp import Llama, llama_get_logits

	LLAMA_AVAILABLE = True
except ImportError:
	LLAMA_AVAILABLE = False
	print("❌ Error: llama-cpp-python no está disponible en este entorno.")
	sys.exit(1)


def get_entropy(probs):
	"""Calcula la entropía de Shannon."""
	return -np.sum(probs * np.log(probs + 1e-9))


def sample_token(logits, temperature=0.7, top_p=0.9, top_k=50, blacklist=None):
	"""Aplica temperatura, top-k, top-p y blacklist a los logits y muestrea un token."""
	logits = np.copy(logits)

	if blacklist:
		for token_id in blacklist:
			logits[token_id] = -float("Inf")

	if temperature <= 0.0:
		pred_id = np.argmax(logits)
		exp_logits = np.exp(logits - np.max(logits))
		probs = exp_logits / np.sum(exp_logits)
		return pred_id, probs[pred_id], probs

	logits = logits / max(temperature, 1e-5)

	exp_logits = np.exp(logits - np.max(logits))
	probs = exp_logits / np.sum(exp_logits)

	if top_k > 0:
		top_k_indices = np.argpartition(probs, -top_k)[-top_k:]
		min_top_prob = np.min(probs[top_k_indices])
		probs[probs < min_top_prob] = 0.0
		sum_probs = np.sum(probs)
		if sum_probs > 0:
			probs = probs / sum_probs

	if top_p < 1.0:
		sorted_indices = np.argsort(probs)[::-1]
		sorted_probs = probs[sorted_indices]
		cumulative_probs = np.cumsum(sorted_probs)

		indices_to_remove = cumulative_probs > top_p
		indices_to_remove[1:] = indices_to_remove[:-1].copy()
		indices_to_remove[0] = False

		probs[sorted_indices[indices_to_remove]] = 0.0
		sum_probs = np.sum(probs)
		if sum_probs > 0:
			probs = probs / sum_probs

	try:
		next_token = np.random.choice(len(probs), p=probs)
		return next_token, probs[next_token], probs
	except ValueError:
		pred_id = np.argmax(logits)
		return pred_id, probs[pred_id], probs


def run_diagnostics():
	workspace = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
	model_path = os.path.join(workspace, "sharing", "models", "gguf", "Falcon3-3B-Instruct-Heretic_Q4_K_M.gguf")

	if not os.path.exists(model_path):
		print(f"❌ Error: No se encontró el modelo GGUF en {model_path}")
		return

	print("🧠 Cargando modelo GGUF Falcon-3B...")
	llm = Llama(model_path=model_path, n_ctx=1024, n_gpu_layers=99, verbose=False)

	prompts = ["<|user|>\nEl sol brilla en el cielo y da mucho...<|assistant|>\n", "<|user|>\nSi sumas dos y dos obtienes...<|assistant|>\n"]

	vocab_size = llm.n_vocab()

	for prompt in prompts:
		cleaned_prompt = prompt.replace("<|user|>\n", "").replace("<|assistant|>\n", "").strip()
		print(f"\n========================================\nPROMPT: '{cleaned_prompt}'\n========================================")

		tokens = llm.tokenize(prompt.encode("utf-8"))
		llm.reset()
		llm.eval(tokens)

		# Generar 10 tokens y mostrar métricas
		current_tokens = list(tokens)
		for step in range(10):
			logits_ptr = llama_get_logits(llm.ctx)
			logits = np.copy(np.ctypeslib.as_array(logits_ptr, shape=(vocab_size,)))

			# Muestrear token (usando temp=0.7, top_k=40, top_p=0.9)
			next_token, prob, probs = sample_token(logits, temperature=0.7, top_k=40, top_p=0.9)
			token_str = llm.detokenize([next_token]).decode("utf-8", errors="ignore")
			entropy = get_entropy(probs)

			# Obtener las 5 alternativas con mayor probabilidad en este paso
			top_5_idx = np.argsort(probs)[::-1][:5]
			top_5_list = []
			for idx in top_5_idx:
				if probs[idx] > 0.0:
					alt_str = llm.detokenize([int(idx)]).decode("utf-8", errors="ignore").replace("\n", "NL")
					top_5_list.append(f"'{alt_str}': {probs[idx]:.4f}")

			# Evaluar lookahead
			llm.eval([next_token])
			next_logits_ptr = llama_get_logits(llm.ctx)
			next_logits = np.copy(np.ctypeslib.as_array(next_logits_ptr, shape=(vocab_size,)))
			exp_logits = np.exp(next_logits - np.max(next_logits))
			next_probs = exp_logits / np.sum(exp_logits)
			max_next_prob = np.max(next_probs)

			print(
				f"Step {step + 1:02d}: Selected='{token_str.replace(chr(10), 'NL')}' | Prob={prob:.4f} | Entropy={entropy:.4f} | LookaheadMaxProb={max_next_prob:.4f}"
			)
			print(f"   Alternatives: {', '.join(top_5_list)}")

			current_tokens.append(next_token)

			if next_token == llm.token_eos():
				print("[EOS alcanzado]")
				break


if __name__ == "__main__":
	run_diagnostics()
