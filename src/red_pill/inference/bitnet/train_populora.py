import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from red_pill.inference.bitnet.translator import SovereignTranslator
from red_pill.inference.bitnet.modeling_bitnet import BitNet4LayerModel
from red_pill.inference.bitnet.dataset_breeder import ReferentialDatasetBreeder

def svd_crossover(parent_a: nn.Module, parent_b: nn.Module, child: nn.Module, alpha: float = 0.5, sigma: float = 0.01):
	"""
	Aplica cruzamiento y perturbación SVD en el espacio de parámetros entrenables
	de parent_a y parent_b, escribiendo el resultado en child.
	"""
	with torch.no_grad():
		for name, param in child.named_parameters():
			if not param.requires_grad:
				continue
			p_a = parent_a.state_dict()[name]
			p_b = parent_b.state_dict()[name]

			# Solo aplicamos SVD a tensores bidimensionales (matrices de pesos de proyección)
			if p_a.ndim == 2:
				# Interpolación lineal de las matrices de peso
				w_avg = alpha * p_a + (1.0 - alpha) * p_b
				try:
					# Descomposición SVD
					u, s, vh = torch.linalg.svd(w_avg, full_matrices=False)
					# Perturbación de valores singulares
					noise = torch.randn_like(s) * sigma
					s_perturbed = s + noise
					s_perturbed.clamp_(min=0.0)
					# Reconstrucción de la matriz cruzada
					w_child = u @ torch.diag(s_perturbed) @ vh
					param.copy_(w_child)
				except Exception:
					# Fallback en caso de error numérico en SVD
					param.copy_(w_avg)
			else:
				# Para vectores (bias, escalas), hacemos interpolación simple con ruido
				noise = torch.randn_like(p_a) * sigma
				param.copy_(alpha * p_a + (1.0 - alpha) * p_b + noise)

def run_arena():
	print("=== 🌋 Iniciando Arena de Comunicación Emergente PopuLoRA (Grado 0) ===")
	device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
	print(f"[Device]: {device}")

	# 1. Cargar el Traductor de Capa 1
	translator = SovereignTranslator()
	vocab_embeddings = translator.get_concept_embeddings()

	# 2. Inicializar Breeder
	breeder = ReferentialDatasetBreeder(translator)

	# 3. Inicializar Población de 4 Alumnos (BitNet de 4 capas)
	pop_size = 4
	population = [
		BitNet4LayerModel(vocab_embeddings=vocab_embeddings, hidden_dim=256, num_layers=4).to(device)
		for _ in range(pop_size)
	]

	# Optimizadores individuales
	optimizers = [
		torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=1e-3)
		for model in population
	]

	# Telemetría de TrueSkill/Fitness
	fitness = np.zeros(pop_size)
	epochs = 5
	steps_per_epoch = 100
	batch_size = 32

	# Parámetros de Gumbel-Softmax
	tau_start = 1.0
	tau_min = 0.1
	total_steps = epochs * steps_per_epoch

	current_step = 0

	for epoch in range(epochs):
		print(f"\n--- Época {epoch + 1}/{epochs} ---")
		epoch_losses = []
		epoch_correct = 0
		epoch_total = 0

		# Matriz de interacción para evaluar fitness
		interactions = np.zeros((pop_size, pop_size))
		successes = np.zeros((pop_size, pop_size))

		for step in range(steps_per_epoch):
			# Decaimiento (annealing) de temperatura Gumbel
			tau = max(tau_min, tau_start * (1.0 - current_step / total_steps))

			# Generar lote de conceptos objetivos y estados emocionales
			concept_targets, concept_token_ids, emotion_targets, emotion_token_ids = breeder.generate_batch(batch_size)
			concept_token_ids_tensor = torch.from_numpy(concept_token_ids).long().to(device)
			emotion_token_ids_tensor = torch.from_numpy(emotion_token_ids).long().to(device)

			# Seleccionar dos agentes distintos de la población
			idx_speaker = np.random.randint(0, pop_size)
			idx_listener = np.random.randint(0, pop_size)
			while idx_listener == idx_speaker:
				idx_listener = np.random.randint(0, pop_size)

			speaker = population[idx_speaker]
			listener = population[idx_listener]

			opt_speaker = optimizers[idx_speaker]
			opt_listener = optimizers[idx_listener]

			opt_speaker.zero_grad()
			opt_listener.zero_grad()

			# 1. El Hablante recibe el target conceptual y el estado emocional, y emite un mensaje de longitud 3
			# Construir entrada: [concept_token_id, emotion_token_id, 0]
			speaker_input = torch.zeros((batch_size, 3), dtype=torch.long, device=device)
			speaker_input[:, 0] = concept_token_ids_tensor
			speaker_input[:, 1] = emotion_token_ids_tensor

			# Generar mensaje discreto diferenciable usando ST-Gumbel-Softmax
			message = speaker.generate_message(speaker_input, tau=tau, hard=True) # (batch_size, 3, 8192)

			# 2. El Oyente recibe el mensaje y predice:
			# - El concepto en el paso 1 (logits[:, 1, :])
			# - La emoción en el paso 2 (logits[:, 2, :])
			logits = listener(message) # (batch_size, 3, 8192)
			pred_concept_logits = logits[:, 1, :] # (batch_size, 8192)
			pred_emotion_logits = logits[:, 2, :] # (batch_size, 8192)

			# 3. Calcular Pérdida conjunta (Entropía cruzada conceptual + afectiva)
			loss_concept = F.cross_entropy(pred_concept_logits, concept_token_ids_tensor)
			loss_emotion = F.cross_entropy(pred_emotion_logits, emotion_token_ids_tensor)
			loss = loss_concept + loss_emotion
			loss.backward()

			# Actualizar parámetros (Capa 3 y proyecciones de Capa 2/4)
			opt_speaker.step()
			opt_listener.step()

			# Registrar telemetría
			epoch_losses.append(loss.item())
			
			preds_concept = torch.argmax(pred_concept_logits, dim=-1)
			preds_emotion = torch.argmax(pred_emotion_logits, dim=-1)
			
			# Entendimiento mutuo exitoso si se descodifican correctamente AMBOS componentes
			correct_joint = ((preds_concept == concept_token_ids_tensor) & (preds_emotion == emotion_token_ids_tensor)).sum().item()

			epoch_correct += correct_joint
			epoch_total += batch_size

			interactions[idx_speaker, idx_listener] += batch_size
			successes[idx_speaker, idx_listener] += correct_joint

			current_step += 1

		# Calcular fitness acumulado de cada agente (accuracy promedio)
		for i in range(pop_size):
			sent_total = interactions[i, :].sum() + interactions[:, i].sum()
			sent_correct = successes[i, :].sum() + successes[:, i].sum()
			fitness[i] = sent_correct / (sent_total + 1e-10)

		avg_loss = np.mean(epoch_losses)
		avg_acc = epoch_correct / epoch_total
		print(f"Pérdida promedio: {avg_loss:.4f} | Entendimiento Mutuo (Accuracy): {avg_acc*100:.2f}%")
		print(f"Fitness de la Población: {['Agent_{}: {:.2f}%'.format(i, f*100) for i, f in enumerate(fitness)]}")

		# Co-evolución: Reemplazar el peor agente si hay suficiente contraste
		worst_idx = np.argmin(fitness)
		best_indices = np.argsort(fitness)[-2:] # Los dos mejores
		print(f"[Evolución] Reemplazando Agent_{worst_idx} (peor fitness) con hijo SVD de Agent_{best_indices[1]} y Agent_{best_indices[0]}")

		svd_crossover(
			parent_a=population[best_indices[1]],
			parent_b=population[best_indices[0]],
			child=population[worst_idx],
			alpha=0.5,
			sigma=0.01
		)

		# Reiniciar el optimizador del peor agente tras la mutación de pesos
		optimizers[worst_idx] = torch.optim.AdamW(
			filter(lambda p: p.requires_grad, population[worst_idx].parameters()),
			lr=1e-3
		)

		# Promoción de grado académica
		if avg_acc >= 0.80:
			print("\n🏆 ¡HIT ALCANZADO! La población ha superado el 80% de entendimiento mutuo.")
			print("PROMOTED TO GRADE 1: Lengua adquirida de forma emergente. Desbloqueando Aritmética.")
			break

if __name__ == "__main__":
	run_arena()
