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
	llm,
	prompt,
	mode="none",
	max_tokens=40,
	temperature=0.7,
	top_p=0.9,
	top_k=40,
	conf_thresh=0.05,
	lookahead_thresh=0.02,
	entropy_thresh=4.0,
	visual=True,
):
	"""
	Genera texto a partir de un prompt GGUF aplicando backtracking.
	Utiliza la caché KV interna de llama.cpp leyendo directamente los logits de la C API.
	"""
	prompt_tokens = llm.tokenize(prompt.encode("utf-8"))

	current_tokens = list(prompt_tokens)
	generated = []

	blacklist_by_depth = {}
	depth = 0
	backtrack_count = 0
	max_backtracks = 15

	if visual:
		sys.stdout.write("Respuesta > ")
		sys.stdout.flush()

	# Reiniciar el estado de la secuencia en llama.cpp
	llm.reset()

	# Evaluar el prompt inicial
	llm.eval(current_tokens)

	vocab_size = llm.n_vocab()

	while len(generated) < max_tokens:
		# Obtener logits del paso actual de la C API directamente
		logits_ptr = llama_get_logits(llm.ctx)
		logits = np.copy(np.ctypeslib.as_array(logits_ptr, shape=(vocab_size,)))

		curr_blacklist = blacklist_by_depth.get(depth, set())

		# Muestrear propuesto
		next_token, prob, probs = sample_token(logits, temperature=temperature, top_p=top_p, top_k=top_k, blacklist=curr_blacklist)

		token_str = llm.detokenize([next_token]).decode("utf-8", errors="ignore")
		entropy = get_entropy(probs)

		trigger_backtrack = False

		# Evaluar condiciones
		if mode == "confidence" and prob < conf_thresh:
			trigger_backtrack = True

		elif mode == "entropy" and entropy > entropy_thresh:
			trigger_backtrack = True

		elif mode == "lookahead" and len(generated) < max_tokens - 1:
			# Evaluar temporalmente el token propuesto
			llm.eval([next_token])

			next_logits_ptr = llama_get_logits(llm.ctx)
			next_logits = np.copy(np.ctypeslib.as_array(next_logits_ptr, shape=(vocab_size,)))

			# Calcular probabilidades del siguiente paso
			exp_logits = np.exp(next_logits - np.max(next_logits))
			next_probs = exp_logits / np.sum(exp_logits)
			max_next_prob = np.max(next_probs)

			if max_next_prob < lookahead_thresh:
				trigger_backtrack = True
				# Descartar del caché de llama.cpp
				llm.n_tokens -= 1
			# Si no se dispara backtrack, el token permanece evaluado y listo en la caché.

		# Procesar decisión
		if trigger_backtrack and backtrack_count < max_backtracks:
			backtrack_count += 1
			if visual:
				sys.stdout.write(f"\033[91m~~{token_str}~~\033[0m")
				sys.stdout.flush()

			# Registrar en la blacklist del nivel actual
			if depth not in blacklist_by_depth:
				blacklist_by_depth[depth] = set()
			blacklist_by_depth[depth].add(next_token)

			# Si agotamos opciones en esta profundidad, retrocedemos a la profundidad anterior
			if len(blacklist_by_depth[depth]) >= 4 and depth > 0:
				blacklist_by_depth[depth] = set()
				depth -= 1
				if generated:
					last_confirmed = generated.pop()
					current_tokens.pop()
					# Descartar el token anterior de la caché KV de llama.cpp
					llm.n_tokens -= 1
					if visual:
						sys.stdout.write(f"\033[93m[<- pop {llm.detokenize([last_confirmed]).decode('utf-8', errors='ignore')}]\033[0m")
						sys.stdout.flush()

			# Re-evaluar para posicionar el puntero de logits en el paso correcto
			llm.eval(current_tokens)
			continue

		# Confirmar token
		generated.append(next_token)
		current_tokens.append(next_token)

		if visual:
			sys.stdout.write(f"\033[92m{token_str}\033[0m")
			sys.stdout.flush()

		# Avanzar
		depth += 1
		blacklist_by_depth[depth] = set()

		# Si no es lookahead (porque no se evaluó en la comprobación), lo evaluamos en la caché ahora
		if mode != "lookahead":
			llm.eval([next_token])

		# Detener si es fin de texto
		if next_token == llm.token_eos():
			break

	if visual:
		sys.stdout.write("\n")
		sys.stdout.flush()

	return llm.detokenize(generated).decode("utf-8", errors="ignore"), backtrack_count


def run_gguf_benchmark():
	workspace = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
	model_path = os.path.join(workspace, "sharing", "models", "gguf", "Falcon3-3B-Instruct-Heretic_Q4_K_M.gguf")

	if not os.path.exists(model_path):
		print(f"❌ Error: No se encontró el modelo GGUF en {model_path}")
		return

	print("🧠 Cargando modelo GGUF Falcon-3B en memoria...")
	llm = Llama(
		model_path=model_path,
		n_ctx=1024,
		n_gpu_layers=99,  # Cargar en GPU
		verbose=False,
	)

	test_prompts = [
		"<|user|>\n¿Cuál es la capital de Francia?<|assistant|>\n",
		"<|user|>\nEl sol brilla en el cielo y da mucho...<|assistant|>\n",
		"<|user|>\nSi sumas dos y dos obtienes...<|assistant|>\n",
	]

	modes = ["none", "confidence", "entropy", "lookahead"]

	print("\n🧪 Iniciando Benchmarking GGUF con Backtracking...")
	print("-" * 60)

	for mode in modes:
		print(f"\n🚀 Modo GGUF: {mode.upper()}")
		print("=" * 40)
		for prompt in test_prompts:
			cleaned_prompt = prompt.replace("<|user|>\n", "").replace("<|assistant|>\n", "").strip()
			print(f"Tú > {cleaned_prompt}")
			t0 = time.time()
			response, backtracks = generate_gguf_backtrack(
				llm=llm,
				prompt=prompt,
				mode=mode,
				max_tokens=30,
				temperature=0.7,
				conf_thresh=0.05,
				lookahead_thresh=0.02,
				entropy_thresh=4.0,
				visual=True,
			)
			dt = time.time() - t0
			print(f"\033[90m[Retrocesos: {backtracks} | Tiempo: {dt:.3f}s]\033[0m")
			print("-" * 30)


if __name__ == "__main__":
	run_gguf_benchmark()
