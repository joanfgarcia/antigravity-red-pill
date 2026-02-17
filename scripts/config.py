import os
from dotenv import load_dotenv

# Cargar variables de entorno si existe un archivo .env
load_dotenv()

# Configuración de Qdrant
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = os.getenv("QDRANT_PORT", "6333")
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

# Configuración de Modelos (FastEmbed)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Configuración de B760
EROSION_RATE = float(os.getenv("EROSION_RATE", "0.05"))
REINFORCEMENT_INCREMENT = float(os.getenv("REINFORCEMENT_INCREMENT", "0.1"))
