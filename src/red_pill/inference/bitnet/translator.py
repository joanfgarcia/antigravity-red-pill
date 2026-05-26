import os
import json
import numpy as np
from fastembed import TextEmbedding

class SovereignTranslator:
	"""
	Capa 1: Traductor Soberano (Puente Humano-Concepto).
	Gestiona un vocabulario discreto de exactamente 8.192 conceptos vectoriales
	utilizando fastembed para mapear texto humano a Token IDs mediante similitud coseno.
	"""

	VOCAB_SIZE = 8192
	EMBED_DIM = 384

	def __init__(self, storage_dir: str = None):
		if storage_dir is None:
			from red_pill.core.paths import get_data_dir
			self.storage_dir = str(get_data_dir() / "curriculum")
		else:
			self.storage_dir = storage_dir

		os.makedirs(self.storage_dir, exist_ok=True)
		self.vocab_path = os.path.join(self.storage_dir, "vocab.json")
		self.embeddings_path = os.path.join(self.storage_dir, "vocab_embeddings.npy")

		self.model = TextEmbedding()
		self.vocab: list[str] = []
		self.embeddings: np.ndarray = np.empty((0, self.EMBED_DIM))

		self._load_or_create_vocab()

	def _generate_core_lexicon(self) -> list[str]:
		"""Genera la lista de palabras base en español e inglés para el autocurrículo."""
		conjunctions = [
			"y", "o", "pero", "porque", "si", "entonces", "aunque", "sino", "mas", "como", "cuando",
			"donde", "and", "or", "but", "because", "if", "then", "although", "since", "how", "when", "where"
		]
		prepositions = [
			"a", "ante", "bajo", "con", "contra", "de", "desde", "en", "entre", "hacia", "hasta", "para",
			"por", "segun", "sin", "sobre", "tras", "of", "to", "in", "for", "on", "with", "at", "by", "from",
			"about", "into", "through"
		]
		pronouns = [
			"el", "la", "los", "las", "un", "una", "unos", "unas", "yo", "tu", "ella", "nosotros", "ellos",
			"mi", "su", "este", "ese", "aquel", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
			"us", "them", "my", "your", "his", "its", "this", "that"
		]
		math_ops = [
			"+", "-", "*", "/", "=", ">", "<", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
			"suma", "resta", "multiplicar", "dividir", "igual", "mas", "menos", "cero", "uno", "dos", "tres"
		]
		nouns_verbs = [
			"gato", "perro", "casa", "árbol", "agua", "fuego", "tierra", "aire", "sol", "luna", "cielo",
			"mar", "río", "montaña", "bosque", "persona", "hombre", "mujer", "niño", "niña", "padre", "madre",
			"amigo", "enemigo", "vida", "muerte", "tiempo", "espacio", "número", "verdad", "falsedad", "lógica",
			"ciencia", "historia", "geografía", "filosofía", "lenguaje", "palabra", "frase", "libro", "escritura",
			"lectura", "habla", "comunicación", "consenso", "peligro", "seguridad", "búnker", "agente", "minion",
			"córtex", "red", "silicio", "hardware", "código", "python", "cat", "dog", "house", "tree", "water",
			"fire", "earth", "air", "sun", "moon", "sky", "sea", "river", "mountain", "forest", "person", "man",
			"woman", "child", "father", "mother", "friend", "life", "death", "time", "space", "number", "truth",
			"logic", "science", "history", "geography", "philosophy", "language", "word", "sentence", "book",
			"writing", "reading", "speech", "communication", "consensus", "danger", "safety", "bunker", "agent",
			"cortex", "network", "silicon", "code", "run", "stop", "eval", "grammar", "syntax", "verb", "noun",
			"miedo", "alegría", "ira", "tristeza", "dolor", "hambre", "fear", "joy", "anger", "sadness", "pain", "hunger"
		]

		core = list(set(conjunctions + prepositions + pronouns + math_ops + nouns_verbs))
		core.sort()
		return core

	def _load_or_create_vocab(self):
		"""Carga el vocabulario y embeddings si existen; de lo contrario, los genera."""
		if os.path.exists(self.vocab_path) and os.path.exists(self.embeddings_path):
			with open(self.vocab_path, "r", encoding="utf-8") as f:
				self.vocab = json.load(f)
			self.embeddings = np.load(self.embeddings_path)
			if len(self.vocab) == self.VOCAB_SIZE and self.embeddings.shape == (self.VOCAB_SIZE, self.EMBED_DIM):
				return

		# Generar nuevo vocabulario de tamaño fijo 8192
		core_lexicon = self._generate_core_lexicon()
		self.vocab = list(core_lexicon)

		# Rellenar con tokens secuenciales hasta 8192
		idx = 0
		while len(self.vocab) < self.VOCAB_SIZE:
			candidate = f"token_{idx}"
			if candidate not in self.vocab:
				self.vocab.append(candidate)
			idx += 1

		# Generar embeddings usando FastEmbed
		print(f"[SovereignTranslator] Generando embeddings para {self.VOCAB_SIZE} conceptos...")
		embeddings_list = [e.tolist() if hasattr(e, "tolist") else e for e in self.model.embed(self.vocab)]
		self.embeddings = np.array(embeddings_list, dtype=np.float32)

		# Guardar en disco para futuras ejecuciones
		with open(self.vocab_path, "w", encoding="utf-8") as f:
			json.dump(self.vocab, f, ensure_ascii=False, indent=4)
		np.save(self.embeddings_path, self.embeddings)
		print("[SovereignTranslator] Vocabulario y embeddings guardados con éxito.")

	def encode(self, text: str) -> list[int]:
		"""Mapea una oración a una lista de Token IDs por similitud de coseno en embeddings."""
		# Limpiar y tokenizar por palabras simples
		words = text.lower().replace(",", " ").replace(".", " ").replace("?", " ").replace("!", " ").split()
		if not words:
			return []

		# Obtener embeddings de las palabras de entrada
		input_embeds = np.array([e.tolist() if hasattr(e, "tolist") else e for e in self.model.embed(words)], dtype=np.float32)

		# Normalizar embeddings de entrada y de vocabulario para similitud coseno rápida
		input_norm = input_embeds / (np.linalg.norm(input_embeds, axis=1, keepdims=True) + 1e-10)
		vocab_norm = self.embeddings / (np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-10)

		# Similitud coseno: multiplicación matricial (len(words) x 8192)
		similarities = np.dot(input_norm, vocab_norm.T)

		# Tomar el índice con mayor similitud para cada palabra
		token_ids = np.argmax(similarities, axis=1).tolist()
		return token_ids

	def decode(self, token_ids: list[int]) -> str:
		"""Decodifica una lista de Token IDs de vuelta a conceptos legibles separados por espacio."""
		decoded_words = []
		for tid in token_ids:
			if 0 <= tid < self.VOCAB_SIZE:
				decoded_words.append(self.vocab[tid])
			else:
				decoded_words.append("<unk>")
		return " ".join(decoded_words)

	def get_concept_embeddings(self) -> np.ndarray:
		"""Devuelve la matriz de embeddings del vocabulario completo (8192 x 384)."""
		return self.embeddings

if __name__ == "__main__":
	# Prueba rápida
	translator = SovereignTranslator()
	test_text = "El gato come comida en el búnker y corre peligro si hay fuego."
	tokens = translator.encode(test_text)
	decoded = translator.decode(tokens)
	print(f"Texto original: '{test_text}'")
	print(f"Token IDs: {tokens}")
	print(f"Decodificado:   '{decoded}'")
