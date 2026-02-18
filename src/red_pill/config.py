import os
from dotenv import load_dotenv

# Load environment variables if .env exists
load_dotenv()

# Qdrant Configuration
# Qdrant Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

# Model Configuration (FastEmbed)
# Model Configuration (FastEmbed)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "384"))

# B760 Logic Configuration
# B760 Logic Configuration
DECAY_STRATEGY = os.getenv("DECAY_STRATEGY", "linear")  # Options: linear, exponential
if DECAY_STRATEGY not in ("linear", "exponential"):
    raise ValueError(f"Invalid DECAY_STRATEGY: {DECAY_STRATEGY}. Must be 'linear' or 'exponential'.")
EROSION_RATE = float(os.getenv("EROSION_RATE", "0.05"))
REINFORCEMENT_INCREMENT = float(os.getenv("REINFORCEMENT_INCREMENT", "0.1"))
PROPAGATION_FACTOR = float(os.getenv("PROPAGATION_FACTOR", "0.5"))  # Reinforcement fraction for associations
IMMUNITY_THRESHOLD = float(os.getenv("IMMUNITY_THRESHOLD", "10.0"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
