import numpy as np
from red_pill.inference.bitnet.translator import SovereignTranslator

class ReferentialDatasetBreeder:
	"""
	Breeder de Datasets Académicos y de Interacción.
	Genera los lotes de "conceptos objetivo" y "estados emocionales" para el juego referencial del Grado 0.
	"""

	def __init__(self, translator: SovereignTranslator):
		self.translator = translator

		# Conceptos físicos objetivos
		self.target_concepts = [
			"gato", "perro", "casa", "árbol", "agua", "fuego", "tierra", "aire",
			"sol", "luna", "peligro", "seguridad", "búnker", "agente", "código"
		]

		# Estados afectivos/fisiológicos objetivos
		self.target_emotions = [
			"miedo", "alegría", "ira", "tristeza", "dolor", "hambre"
		]

		# Token IDs de Capa 1 para conceptos físicos
		self.target_concept_token_ids = []
		for concept in self.target_concepts:
			tids = self.translator.encode(concept)
			self.target_concept_token_ids.append(tids[0] if tids else 0)

		# Token IDs de Capa 1 para estados emocionales
		self.target_emotion_token_ids = []
		for emotion in self.target_emotions:
			tids = self.translator.encode(emotion)
			self.target_emotion_token_ids.append(tids[0] if tids else 0)

		self.num_concepts = len(self.target_concepts)
		self.num_emotions = len(self.target_emotions)

	def generate_batch(self, batch_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
		"""
		Genera un lote aleatorio para el juego de señalización dual.
		Devuelve:
		- concept_targets: Índices locales de conceptos (batch_size,)
		- concept_token_ids: Token IDs de Capa 1 de conceptos (batch_size,)
		- emotion_targets: Índices locales de emociones (batch_size,)
		- emotion_token_ids: Token IDs de Capa 1 de emociones (batch_size,)
		"""
		concept_targets = np.random.randint(0, self.num_concepts, size=(batch_size,))
		concept_token_ids = np.array([self.target_concept_token_ids[c] for c in concept_targets], dtype=np.int64)

		emotion_targets = np.random.randint(0, self.num_emotions, size=(batch_size,))
		emotion_token_ids = np.array([self.target_emotion_token_ids[e] for e in emotion_targets], dtype=np.int64)

		return concept_targets, concept_token_ids, emotion_targets, emotion_token_ids

	def get_concept_name(self, class_idx: int) -> str:
		"""Devuelve el nombre humano del concepto objetivo."""
		if 0 <= class_idx < self.num_concepts:
			return self.target_concepts[class_idx]
		return "desconocido"

	def get_emotion_name(self, class_idx: int) -> str:
		"""Devuelve el nombre humano del estado afectivo."""
		if 0 <= class_idx < self.num_emotions:
			return self.target_emotions[class_idx]
		return "desconocido"
