import os
from dotenv import load_dotenv

load_dotenv()

# QDRANT
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
QDRANT_SCHEME = os.getenv("QDRANT_SCHEME", "http")
QDRANT_URL = f"{QDRANT_SCHEME}://{QDRANT_HOST}:{QDRANT_PORT}"

# MODELS
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "384"))

# B760 LOGIC
DECAY_STRATEGY = os.getenv("DECAY_STRATEGY", "linear")
if DECAY_STRATEGY not in ("linear", "exponential"):
	raise ValueError(f"Invalid DECAY_STRATEGY: {DECAY_STRATEGY}")

EROSION_RATE = float(os.getenv("EROSION_RATE", "0.05"))
REINFORCEMENT_INCREMENT = float(os.getenv("REINFORCEMENT_INCREMENT", "0.1"))
PROPAGATION_FACTOR = float(os.getenv("PROPAGATION_FACTOR", "0.5"))
IMMUNITY_THRESHOLD = float(os.getenv("IMMUNITY_THRESHOLD", "10.0"))

# LOGGING
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# DEEP RECALL
DEEP_RECALL_TRIGGERS = [
	"don't you remember",
	"¿no te acuerdas?",
	"deep recall",
	"do you really not remember?",
	"esfuerzate en recordar",
	"try hard!"
]

# METABOLISM
METABOLISM_ENABLED = os.getenv("METABOLISM_ENABLED", "True").lower() == "true"
METABOLISM_COOLDOWN = int(os.getenv("METABOLISM_COOLDOWN", "3600"))
METABOLISM_AUTO_COLLECTIONS = os.getenv("METABOLISM_AUTO_COLLECTIONS", "work_memories,social_memories").split(",")
METABOLISM_STATE_FILE = os.path.expanduser("~/.red_pill_metabolism")
