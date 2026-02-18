import os
from dotenv import load_dotenv

# Load environment variables if .env exists
load_dotenv()

# Qdrant Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = os.getenv("QDRANT_PORT", "6333")
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

# Model Configuration (FastEmbed)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# B760 Logic Configuration
DECAY_STRATEGY = os.getenv("DECAY_STRATEGY", "linear")  # Options: linear, exponential
EROSION_RATE = float(os.getenv("EROSION_RATE", "0.05"))
REINFORCEMENT_INCREMENT = float(os.getenv("REINFORCEMENT_INCREMENT", "0.1"))
IMMUNITY_THRESHOLD = float(os.getenv("IMMUNITY_THRESHOLD", "10.0"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
