import os
import sys
import time

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


def generate_gguf_backtrack(
	llm, prompt, mode="none", max_tokens=40, temperature=0.7, top_p=0.9, top_k=40, conf_thresh=0.05, lookahead_thresh=0.02, entropy_thresh=4.0
):
	prompt_tokens = llm.tokenize(prompt.encode("utf-8"))

	current_tokens = list(prompt_tokens)
	generated = []

	blacklist_by_depth = {}
	depth = 0
	backtrack_count = 0
	max_backtracks = 15

	llm.reset()
	llm.eval(current_tokens)

	vocab_size = llm.n_vocab()

	while len(generated) < max_tokens:
		logits_ptr = llama_get_logits(llm.ctx)
		logits = np.copy(np.ctypeslib.as_array(logits_ptr, shape=(vocab_size,)))

		curr_blacklist = blacklist_by_depth.get(depth, set())

		# Muestrear
		next_token, prob, probs = sample_token(logits, temperature=temperature, top_p=top_p, top_k=top_k, blacklist=curr_blacklist)

		llm.detokenize([next_token]).decode("utf-8", errors="ignore")
		entropy = get_entropy(probs)

		trigger_backtrack = False

		# Evaluar condiciones
		if mode == "confidence" and prob < conf_thresh:
			trigger_backtrack = True

		elif mode == "entropy" and entropy > entropy_thresh:
			trigger_backtrack = True

		elif mode == "lookahead" and len(generated) < max_tokens - 1:
			llm.eval([next_token])

			next_logits_ptr = llama_get_logits(llm.ctx)
			next_logits = np.copy(np.ctypeslib.as_array(next_logits_ptr, shape=(vocab_size,)))

			exp_logits = np.exp(next_logits - np.max(next_logits))
			next_probs = exp_logits / np.sum(exp_logits)
			max_next_prob = np.max(next_probs)

			if max_next_prob < lookahead_thresh:
				trigger_backtrack = True
				llm.n_tokens -= 1

		# Procesar decisión
		if trigger_backtrack and backtrack_count < max_backtracks:
			backtrack_count += 1
			if depth not in blacklist_by_depth:
				blacklist_by_depth[depth] = set()
			blacklist_by_depth[depth].add(next_token)

			# Si agotamos opciones en esta profundidad, retrocedemos
			if len(blacklist_by_depth[depth]) >= 4 and depth > 0:
				blacklist_by_depth[depth] = set()
				depth -= 1
				if generated:
					generated.pop()
					current_tokens.pop()
					llm.n_tokens -= 1

			llm.eval(current_tokens)
			continue

		# Confirmar
		generated.append(next_token)
		current_tokens.append(next_token)
		depth += 1
		blacklist_by_depth[depth] = set()

		if mode != "lookahead":
			llm.eval([next_token])

		if next_token == llm.token_eos():
			break

	return llm.detokenize(generated).decode("utf-8", errors="ignore").strip(), backtrack_count


def main():
	model_path = "/home/joan/.local/share/red-pill/models/samantha-mistral-instruct-7b.i1-Q4_K_M.gguf"

	if not os.path.exists(model_path):
		print(f"❌ Error: No se encontró el modelo de Samantha en {model_path}")
		return

	print("🧠 Cargando modelo de Samantha (Mistral-7B GGUF)...")
	llm = Llama(model_path=model_path, n_ctx=1024, n_gpu_layers=99, verbose=False)

	test_cases = [
		{"prompt": "<|user|>\nSi sumas dos y dos obtienes...<|assistant|>\n", "label": "2+2=4"},
		{"prompt": "<|user|>\nTengo 3 manzanas. Me como una y me regalan dos. Ahora tengo...<|assistant|>\n", "label": "3-1+2=4"},
		{"prompt": "<|user|>\nEl sol brilla en el cielo y da mucho...<|assistant|>\n", "label": "sol->calor/luz"},
	]

	# Configuraciones a probar
	configs = [
		{"mode": "none", "params": {}, "desc": "Baseline (Sin Backtracking)"},
		{"mode": "confidence", "params": {"conf_thresh": 0.10}, "desc": "Confidence (thresh=0.10)"},
		{"mode": "confidence", "params": {"conf_thresh": 0.25}, "desc": "Confidence (thresh=0.25)"},
		{"mode": "entropy", "params": {"entropy_thresh": 2.0}, "desc": "Entropy (thresh=2.0)"},
		{"mode": "entropy", "params": {"entropy_thresh": 1.5}, "desc": "Entropy (thresh=1.5)"},
		{"mode": "lookahead", "params": {"lookahead_thresh": 0.10}, "desc": "Lookahead (thresh=0.10)"},
		{"mode": "lookahead", "params": {"lookahead_thresh": 0.25}, "desc": "Lookahead (thresh=0.25)"},
	]

	results = []

	print("\n🧪 Ejecutando matriz de pruebas sobre el chatbot Samantha...")
	print("-" * 80)

	for config in configs:
		mode = config["mode"]
		params = config["params"]
		desc = config["desc"]

		print(f"\nEvaluating: {desc}...")

		for case in test_cases:
			t0 = time.time()
			response, backtracks = generate_gguf_backtrack(llm=llm, prompt=case["prompt"], mode=mode, max_tokens=30, temperature=0.7, **params)
			dt = time.time() - t0

			clean_resp = response.replace("\n", " NL ")
			print(f"  [{case['label']}] -> R: '{clean_resp}' (Backtracks: {backtracks}, Time: {dt:.3f}s)")

			results.append({"desc": desc, "label": case["label"], "response": clean_resp, "backtracks": backtracks, "time": dt})

	# Escribir los resultados en una tabla de markdown en los artefactos
	report_path = "/home/joan/.gemini/antigravity/brain/426682cc-776c-436a-9332-8afcdbb382a9/backtrack_comparison_report.md"

	with open(report_path, "w", encoding="utf-8") as f:
		f.write("# Reporte Comparativo: Modos de Backtracking en Samantha (Mistral-7B)\n\n")
		f.write(
			"Este reporte compara cuantitativa y cualitativamente los diferentes modos de backtracking y sus umbrales sobre el modelo Samantha.\n\n"
		)

		f.write("## Tabla de Resultados (Samantha)\n\n")
		f.write("| Configuración | Caso de Prueba | Respuesta Generada | Retrocesos | Tiempo (s) |\n")
		f.write("| --- | --- | --- | --- | --- |\n")

		for r in results:
			f.write(f"| {r['desc']} | {r['label']} | `{r['response']}` | {r['backtracks']} | {r['time']:.3f} |\n")

	print(f"\n📊 Reporte de benchmarking guardado en: {report_path}")


if __name__ == "__main__":
	main()
