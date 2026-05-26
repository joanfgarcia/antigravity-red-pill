import argparse
import os
import sys

import numpy as np
import torch

# Añadir el directorio src al path para poder importar
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from red_pill.inference.bitnet.modeling_bitnet import BitNet4LayerModel
from red_pill.inference.bitnet.translator import SovereignTranslator


def print_header(title: str):
	print("\n================================================================================")
	print(f"🔬 LENTE: {title}")
	print("================================================================================")


def inspect_synapses(model: torch.nn.Module):
	print_header("ESTRUCTURA SINÁPTICA TERNARIA")

	total_weights = 0
	val_neg_1 = 0
	val_0 = 0
	val_1 = 0
	other_vals = 0

	for name, param in model.named_parameters():
		if "weight" in name and param.ndim == 2:
			# Cuantizar usando el estimador STE del modelo
			scale = param.abs().mean().clamp(min=1e-5).item()
			quant = (param / scale).round().clamp(-1, 1)

			w_flat = quant.detach().cpu().numpy().flatten()
			total_weights += len(w_flat)

			val_neg_1 += np.sum(w_flat == -1)
			val_0 += np.sum(w_flat == 0)
			val_1 += np.sum(w_flat == 1)
			other_vals += np.sum((w_flat != -1) & (w_flat != 0) & (w_flat != 1))

			print(f"Matriz: {name:40s} | Shape: {str(list(param.shape)):15s} | Escala de Cuantización: {scale:.5f}")

	print("-" * 80)
	print(f"Total Parámetros de Proyección Analizados: {total_weights:,}")
	if total_weights > 0:
		p_neg = val_neg_1 / total_weights * 100
		p_zero = val_0 / total_weights * 100
		p_pos = val_1 / total_weights * 100
		p_other = other_vals / total_weights * 100

		print(f"  • Pesos Ternarios -1 : {val_neg_1:10,} ({p_neg:6.2f}%)  [■■■■■■■■■□]")
		print(f"  • Pesos Ternarios  0 : {val_0:10,} ({p_zero:6.2f}%)  [■■■■■□□□□□]")
		print(f"  • Pesos Ternarios +1 : {val_1:10,} ({p_pos:6.2f}%)  [■■■■■■■■■□]")
		if p_other > 0:
			print(f"  • Pesos Flotantes/Otros: {other_vals:10,} ({p_other:6.2f}%)  [! WARNING !]")
		else:
			print("  ✓ Estado de Integridad: TERNARIO PURO (100% verificado)")


def inspect_homeostasis(model: torch.nn.Module):
	print_header("DINÁMICA HOMEOSTÁTICA DE SILICIO (SIMULACIÓN)")

	# Parámetros metabólicos simulados
	energia = 100.0
	temperatura = 35.0
	integridad = 100.0
	costo_forward = 4.5
	decaimiento_termico = 0.8

	print(f"Estado Inicial: Energía={energia:.1f}% | Temp={temperatura:.1f}°C | Integridad={integridad:.1f}%")
	print("-" * 80)
	print(f"{'PASO':6s} | {'ACCIÓN':20s} | {'ENERGÍA':10s} | {'TEMPERATURA':12s} | {'INTEGRIDAD':10s} | {'ESTADO EMOCIONAL'}")
	print("-" * 80)

	for paso in range(1, 6):
		# Simular forward pass de alta carga
		energia -= costo_forward
		# Aumento de temperatura basado en el tamaño oculto y capas del modelo
		temperatura += (model.hidden_dim / 32.0) * len(model.core_layers) * 0.1
		temperatura -= decaimiento_termico

		# Afectar integridad si la temperatura cruza 45°C
		if temperatura > 45.0:
			danio = (temperatura - 45.0) * 1.5
			integridad -= danio

		# Determinar estado emocional
		emocion = "ALEGRE"
		if energia < 80.0:
			emocion = "HAMBRE"
		if energia < 50.0 or integridad < 90.0:
			emocion = "DOLOR"
		if temperatura > 42.0:
			emocion = "MIEDO"
		if integridad < 50.0:
			emocion = "CRÍTICO"

		print(f"#{paso:02d}   | Computación Arena   | {energia:8.1f}% | {temperatura:10.1f}°C | {integridad:8.1f}%   | {emocion}")

	print("-" * 80)
	print(f"Simulación Homeostática Finalizada. Consumo total de glucosa de silicio: {(100.0 - energia):.1f}%")


def inspect_linguistics(model: torch.nn.Module, translator: SovereignTranslator):
	print_header("SONDA LINGÜÍSTICA DE CAPA 1")

	concept_test = "fuego"
	emotion_test = "miedo"

	concept_ids = translator.encode(concept_test)
	emotion_ids = translator.encode(emotion_test)

	if not concept_ids or not emotion_ids:
		print("Error: No se pudieron codificar los conceptos de prueba.")
		return

	c_id = concept_ids[0]
	e_id = emotion_ids[0]

	print("Entrada del Hablante:")
	print(f"  • Concepto Objetivo: '{concept_test}' (ID {c_id})")
	print(f"  • Estado Afectivo:   '{emotion_test}' (ID {e_id})")

	device = next(model.parameters()).device
	speaker_input = torch.zeros((1, 3), dtype=torch.long, device=device)
	speaker_input[0, 0] = c_id
	speaker_input[0, 1] = e_id

	model.eval()
	with torch.no_grad():
		# Generar mensaje (one-hot relajado)
		message = model.generate_message(speaker_input, tau=0.1, hard=True)
		msg_tokens = message.argmax(dim=-1)[0].tolist()

		# Decodificar mensaje
		msg_words = translator.decode(msg_tokens)
		print("\nMensaje emitido por el Hablante (Capa 1):")
		print(f"  • Token IDs: {msg_tokens}")
		print(f"  • Conceptos: '{msg_words}'")

		# Probar descodificación del Oyente
		logits = model(message)
		pred_c_id = logits[0, 1, :].argmax().item()
		pred_e_id = logits[0, 2, :].argmax().item()

		print("\nDescodificación del Oyente (Empatía):")
		print(f"  • Concepto predicho: '{translator.decode([pred_c_id])}' (ID {pred_c_id})")
		print(f"  • Emoción predicha:  '{translator.decode([pred_e_id])}' (ID {pred_e_id})")

		match_c = pred_c_id == c_id
		match_e = pred_e_id == e_id

		print("-" * 80)
		print("Resultado del Juego Referencial Afectivo:")
		print(f"  • Entendimiento Conceptual: {'✓ ÉXITO' if match_c else '✗ ERROR'}")
		print(f"  • Alineación Afectiva (Empatía): {'✓ ÉXITO' if match_e else '✗ ERROR'}")
		if match_c and match_e:
			print("  ✓ Recompensa conjunta: R = 1.0 (Entendimiento Mutuo Pleno)")
		elif match_c:
			print("  ⚠ Recompensa penalizada: R = 0.3 (Falta de empatía o reward hacking)")
		else:
			print("  ✗ Recompensa: R = 0.0 (Fallo en la comunicación)")


def inspect_svd(model: torch.nn.Module):
	print_header("ESPECTRO DE VALORES SINGULARES (SVD)")

	# Tomar la primera capa del core para analizar
	analyzed = False
	for name, param in model.named_parameters():
		if "core_layers.0.attn.q_proj.weight" in name:
			try:
				w = param.detach().cpu().float()
				u, s, vh = torch.linalg.svd(w, full_matrices=False)
				s_np = s.numpy()

				print(f"Matriz Analizada: {name}")
				print(f"Rango Matemático: {len(s_np)} | Valores Singulares Mayores (Top 10):")
				for idx, val in enumerate(s_np[:10]):
					bar = "■" * int(min(20, val * 10))
					print(f"  σ_{idx + 1:02d} : {val:8.4f} {bar}")

				# Calcular entropía espectral aproximada
				s_norm = s_np / np.sum(s_np)
				entropy = -np.sum(s_norm * np.log(s_norm + 1e-10))
				print(f"\nEntropía Espectral del Peso: {entropy:.4f} (Indica dispersión de información)")
				analyzed = True
			except Exception as e:
				print(f"Error en descomposición SVD: {e}")
			break

	if not analyzed:
		print("No se encontró la matriz q_proj de la primera capa del Core para realizar SVD.")


def main():
	parser = argparse.ArgumentParser(description="Microscopio Cognitivo del Búnker - Inspecciona Especímenes BitNet.")
	parser.add_argument("--specimen", type=str, help="Ruta al archivo .pt del espécimen a inspeccionar.")
	parser.add_argument("--hidden_dim", type=int, default=256, help="Dimensión oculta (por defecto 256).")
	parser.add_argument("--num_layers", type=int, default=4, help="Número de capas (por defecto 4).")
	args = parser.parse_args()

	print("================================================================================")
	print("                     🔬 MICROSCOPIO COGNITIVO DEL BÚNKER v1                     ")
	print("================================================================================")

	translator = SovereignTranslator()
	vocab_embeddings = translator.get_concept_embeddings()

	if args.specimen and os.path.exists(args.specimen):
		print(f"Cargando espécimen desde: {args.specimen}")
		model = BitNet4LayerModel(vocab_embeddings=vocab_embeddings, hidden_dim=args.hidden_dim, num_layers=args.num_layers)
		try:
			model.load_state_dict(torch.load(args.specimen, map_location="cpu"))
			print("✓ Espécimen cargado con éxito.")
		except Exception as e:
			print(f"Error al cargar pesos del espécimen: {e}. Inicializando sujeto virgen para diagnóstico.")
			model = BitNet4LayerModel(vocab_embeddings=vocab_embeddings, hidden_dim=args.hidden_dim, num_layers=args.num_layers)
	else:
		print("Inicializando sujeto virgen de control (Kaoting Uniforme)...")
		model = BitNet4LayerModel(vocab_embeddings=vocab_embeddings, hidden_dim=args.hidden_dim, num_layers=args.num_layers)

	inspect_synapses(model)
	inspect_homeostasis(model)
	inspect_linguistics(model, translator)
	inspect_svd(model)


if __name__ == "__main__":
	main()
