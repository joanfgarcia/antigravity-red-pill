import os

from dotenv import load_dotenv

load_dotenv()

# QDRANT
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
QDRANT_SCHEME = os.getenv("QDRANT_SCHEME", "http")
QDRANT_URL = f"{QDRANT_SCHEME}://{QDRANT_HOST}:{QDRANT_PORT}"

_run_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")
DAEMON_SOCKET_PATH = os.getenv("DAEMON_SOCKET_PATH", os.path.join(_run_dir, "red_pill_memory.sock"))

# MODELS
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "384"))

# B760 LOGIC
DECAY_STRATEGY = os.getenv("DECAY_STRATEGY", "linear")
if DECAY_STRATEGY not in ("linear", "exponential"):
	raise ValueError(f"Invalid DECAY_STRATEGY: {DECAY_STRATEGY}")

# EROSION_RATE: fraction of reinforcement_score removed per erosion cycle.
# Default 0.01 targets ~100 cycles before a neutral memory (score=1.0) dies.
# At 1 cycle/hour = ~4 days minimum. Tune upward for aggressive forgetting.
# NOTE: was 0.05 in development/testing. 0.01 is the production target.
EROSION_RATE = float(os.getenv("EROSION_RATE", "0.01"))
REINFORCEMENT_INCREMENT = float(os.getenv("REINFORCEMENT_INCREMENT", "0.1"))
PROPAGATION_FACTOR = float(os.getenv("PROPAGATION_FACTOR", "0.5"))
IMMUNITY_THRESHOLD = float(os.getenv("IMMUNITY_THRESHOLD", "10.0"))

# EMOTIONAL_SEED_FACTOR: multiplier applied to initial reinforcement_score for
# non-neutral memories with intensity > 1.0. Higher values give emotional
# memories more runway before erosion. At SEED_FACTOR=3.0 and intensity=10,
# orange memories start at score ~5.5 (vs 1.0 for neutral).
# At production EROSION_RATE=0.01: score=9.0 → 600 hours ≈ 25 days survival.
EMOTIONAL_SEED_FACTOR = float(os.getenv("EMOTIONAL_SEED_FACTOR", "3.0"))


# LOGGING
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# DEEP RECALL & WAKE CALLS
# 'despierta' and 'wake up' are the unalterable synthetic-organic symbiosis triggers.
_default_triggers = "don't you remember,¿no te acuerdas?,deep recall,do you really not remember?,esfuerzate en recordar,try hard!"
_env_triggers = os.getenv("DEEP_RECALL_TRIGGERS", _default_triggers)

DEEP_RECALL_TRIGGERS = [
	"despierta",
	"despierta neo",
	"wake up"
] + [t.strip().lower() for t in _env_triggers.split(",") if t.strip()]

# METABOLISM
METABOLISM_ENABLED = os.getenv("METABOLISM_ENABLED", "True").lower() == "true"
METABOLISM_COOLDOWN = int(os.getenv("METABOLISM_COOLDOWN", "3600"))
METABOLISM_AUTO_COLLECTIONS = os.getenv("METABOLISM_AUTO_COLLECTIONS", "work_memories,social_memories,story_memories").split(",")
METABOLISM_STATE_FILE = os.path.expanduser("~/.red_pill_metabolism")
# If the bunker has been idle for more than this many seconds, a TTL refresh
# is triggered before erosion to prevent mass-deletion after long absences.
# Default: 7 days (7 * 24 * 3600).
ABSENCE_THRESHOLD = int(os.getenv("ABSENCE_THRESHOLD", str(7 * 24 * 3600)))

# EMOTIONAL CHROMA (v4.2.0)
DEFAULT_COLOR = "gray"
DEFAULT_EMOTION = "neutral"
EMOTIONAL_DECAY_MULTIPLIERS = {
	"orange": 1.5,  # Anxiety: decays faster if not reinforced
	"yellow": 0.5,  # Joy: persists longer
	"purple": 2.0,  # Ennui: garbage collected quickly
	"cyan": 0.8,    # Envy/Evolution: focused persistence
	"blue": 1.0,    # Sadness: standard decay
	"gray": 1.0,    # Neutral: standard decay
}

# CHROMA-TONE MAPPING (v4.2.1)
# Mapping for non-technical narrative refraction.
CHROMA_TONE_MAPPING = {
	"orange": "Vigilant, alert, high risk-awareness, proactive warnings.",
	"yellow": "Optimistic, encouraging, success-focused, warm.",
	"purple": "Minimalist, extremely concise, efficiency-first, no fluff.",
	"cyan": "Visionary, future-oriented, focused on growth and backlog.",
	"blue": "Reflective, empathetic, serious, acknowledging weight.",
	"gray": "Professional, balanced, direct, objective (Standard).",
	"nostalgia": "Respectful, shared legacy focus, acknowledging the long road."
}
