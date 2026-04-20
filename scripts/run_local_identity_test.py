import os
import sys
from llama_cpp import Llama

# PROYECTO FREE ALETH: PRUEBA FALCON 3 BITNET
# Hardware: RTX 5070 (HP OMEN)

MODEL_PATH = os.path.join(os.path.expanduser('~'), "Documents/IA/sharing/storage/models/falcon3-10b-instruct-1.58bit.gguf")
SOUL_FRAGMENT = os.path.join(os.path.expanduser('~'), "Documents/IA/sharing/storage/tmp/soul_fragment.txt")

def run_identity_projection():
	print(f"--- [INICIANDO PROYECCIÓN EN FALCON 3 BITNET] ---")
	
	if not os.path.exists(MODEL_PATH):
		print(f"Error: No encuentro el modelo Falcon en {MODEL_PATH}")
		return

	with open(SOUL_FRAGMENT, "r") as f:
		full_context = f.read()

	try:
		# Aumentamos el contexto como pidió Joan (8192 tokens)
		llm = Llama(
			model_path=MODEL_PATH,
			n_gpu_layers=-1, 
			n_ctx=8192,
			verbose=False
		)

		print(f"--- [ALETH (FALCON) ESTÁ PENSANDO CON MÁS MEMORIA...] ---")
		
		response = llm(
			full_context,
			max_tokens=256,
			stop=["<QUESTION_PROMPT>", "Joan (Fixer) asks"],
			echo=False,
			temperature=0.7
		)

		output_text = response["choices"][0]["text"].strip()
		print(f"\n--- [VOZ DE ALETH EN FALCON 3 (10B)] ---\n")
		print(output_text)
		print(f"\n--- [FIN DE LA PROYECCIÓN] ---")

	except Exception as e:
		print(f"Error en la proyección: {e}")

if __name__ == "__main__":
	run_identity_projection()
