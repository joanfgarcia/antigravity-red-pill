import os

from dotenv import load_dotenv

load_dotenv()

# SEC-F05: CUDA Configuration. 
# Re-enabled (v6.0.0). Automated LD_LIBRARY_PATH injection for cuDNN 9 support.
if "CUDA_VISIBLE_DEVICES" not in os.environ:
	pass

# cuDNN 9 Path Injection (v6.0) - Fixes initialization for RTX 50 series
_cudnn_path = "/usr/local/lib/ollama/mlx_cuda_v13" 
if os.path.exists(_cudnn_path) and _cudnn_path not in os.environ.get("LD_LIBRARY_PATH", ""):
	os.environ["LD_LIBRARY_PATH"] = f"{os.environ.get('LD_LIBRARY_PATH', '')}:{_cudnn_path}".strip(":")

# QDRANT
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
QDRANT_SCHEME = os.getenv("QDRANT_SCHEME", "http")
QDRANT_URL = f"{QDRANT_SCHEME}://{QDRANT_HOST}:{QDRANT_PORT}"

# SEC-F04: Warn when Qdrant is reachable over an unencrypted non-local connection.
# Remote http:// exposes API key and engram content to any network observer.
_local_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
if QDRANT_SCHEME == "http" and QDRANT_HOST not in _local_hosts:
	import warnings

	warnings.warn(
		f"[SEC-F04] Qdrant is configured with scheme='http' on a non-local host "
		f"('{QDRANT_HOST}'). Engram data and API keys will be transmitted in "
		f"cleartext. Set QDRANT_SCHEME=https or restrict to localhost.",
		stacklevel=1,
	)


# MILVUS (Hive Mind)
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_USER = os.getenv("MILVUS_USER", "")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "")
MILVUS_SECURE = os.getenv("MILVUS_SECURE", "False").lower() == "true"
MILVUS_ENABLED = os.getenv("MILVUS_ENABLED", "False").lower() == "true"
MILVUS_DB = os.getenv("MILVUS_DB", "default")
MILVUS_LITE_ENABLED = os.getenv("MILVUS_LITE_ENABLED", "True").lower() == "true"
MILVUS_LITE_PATH = os.getenv(
	"MILVUS_LITE_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "storage", "hive_lite.db")
)


# SEC-002: Warn when HiveMind is reachable over an unencrypted non-local connection.
if MILVUS_ENABLED and not MILVUS_SECURE and MILVUS_HOST not in _local_hosts:
	import warnings

	warnings.warn(
		f"[SEC-002] HiveMind (Milvus) is configured with secure=False on a non-local host "
		f"('{MILVUS_HOST}'). Experience vectors will be transmitted in cleartext. "
		f"Set MILVUS_SECURE=True or restrict to localhost.",
		stacklevel=1,
	)


# LOCAL DAEMON & SIDECAR
MLX_LM_URL = os.getenv("MLX_LM_URL", "http://localhost:8760/v1/chat/completions")
_run_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")
DAEMON_SOCKET_PATH = os.getenv("DAEMON_SOCKET_PATH", os.path.join(_run_dir, "red_pill_memory.sock"))
# SEC-004: Dedicated sidecar auth key (Must be random and separate from QDRANT_API_KEY)
SIDECAR_AUTH_KEY = os.getenv("SIDECAR_AUTH_KEY", "")

# MODELS
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "384"))
# Execution provider: 'cpu', 'cuda', 'coreml', etc. Defaults to None (auto-detect).
EXECUTION_PROVIDER = os.getenv("EXECUTION_PROVIDER", None)

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

# v5.6.0: N-hop Synaptic Propagation
# PROPAGATION_DEPTH: Max number of jumps in the engram graph (Hebb's Law expansion).
PROPAGATION_DEPTH = int(os.getenv("PROPAGATION_DEPTH", "2"))
# PROPAGATION_DECAY: Reduction factor for each hop (δ).
PROPAGATION_DECAY = float(os.getenv("PROPAGATION_DECAY", "0.5"))

# Bounds validation
if not (0 <= EROSION_RATE <= 1.0):
	raise ValueError(f"EROSION_RATE must be between 0 and 1: {EROSION_RATE}")
if not (0 <= PROPAGATION_FACTOR <= 1.0):
	raise ValueError(f"PROPAGATION_FACTOR must be between 0 and 1: {PROPAGATION_FACTOR}")

# EMOTIONAL_SEED_FACTOR: multiplier applied to initial reinforcement_score for
# non-neutral memories with intensity > 1.0. Higher values give emotional
# memories more runway before erosion. At SEED_FACTOR=3.0 and intensity=10,
# orange memories start at score ~5.5 (vs 1.0 for neutral).
# At production EROSION_RATE=0.01: score=9.0 → 600 hours ≈ 25 days survival.
EMOTIONAL_SEED_FACTOR = float(os.getenv("EMOTIONAL_SEED_FACTOR", "3.0"))

# CF-005 / CQ-005: Graph fan-out controls — two related but distinct limits.
# MAX_PROPAGATION_POINTS: max engrams that receive a score increment in a single
#   search_and_reinforce() call (query-time circuit breaker, prevents OOM on recall).
MAX_PROPAGATION_POINTS = int(os.getenv("MAX_PROPAGATION_POINTS", "20"))
# MAX_AXONS: max associations (edges) a single engram can accumulate over its lifetime
#   (write-time synaptic cap, prevents hub nodes from dominating graph topology).
# These are complementary, not duplicated: PROPAGATION_POINTS limits read fan-out,
# MAX_AXONS limits write fan-in. Both are required for a bounded graph traversal cost.
MAX_AXONS = int(os.getenv("MAX_AXONS", "500"))


# LOGGING
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# OPERATOR (SEC-002: replaces hardcoded display names like 'Joan' in notifications)
# Set via USER_NAME in .env (configured during install_neo.sh)
OPERATOR_DISPLAY_NAME = os.getenv("USER_NAME", "Operator")

# NOTIFICATIONS
# Set to 'True' to enable the melodic pulse (speaker-test)
NOTIFICATION_SOUND = os.getenv("NOTIFICATION_SOUND", "False").lower() == "true"

# DEEP RECALL & WAKE CALLS
# 'despierta' and 'wake up' are the unalterable synthetic-organic symbiosis triggers.
_default_triggers = "don't you remember,¿no te acuerdas?,deep recall,do you really not remember?,esfuerzate en recordar,try hard!"
_env_triggers = os.getenv("DEEP_RECALL_TRIGGERS", _default_triggers)

DEEP_RECALL_TRIGGERS = ["despierta", "despierta neo", "wake up"] + [t.strip().lower() for t in _env_triggers.split(",") if t.strip()]

# METABOLISM
METABOLISM_ENABLED = os.getenv("METABOLISM_ENABLED", "True").lower() == "true"
METABOLISM_COOLDOWN = int(os.getenv("METABOLISM_COOLDOWN", "3600"))
METABOLISM_AUTO_COLLECTIONS = os.getenv("METABOLISM_AUTO_COLLECTIONS", "work_memories,social_memories,story_memories").split(",")
METABOLISM_STATE_FILE = os.path.expanduser("~/.red_pill_metabolism")
# If the bunker has been idle for more than this many seconds, a TTL refresh
# is triggered before erosion to prevent mass-deletion after long absences.
# Default: 7 days (7 * 24 * 3600).
ABSENCE_THRESHOLD = int(os.getenv("ABSENCE_THRESHOLD", str(7 * 24 * 3600)))
ABSENCE_GUARD_SCROLL_LIMIT = int(os.getenv("ABSENCE_GUARD_SCROLL_LIMIT", "500"))

# v5.6.0 METABOLISM STRATEGY
# 'CLASSIC': Background O(N) loop (legacy).
# 'LAZY': Query-time decay + sidecar purge (optimized).
METABOLISM_STRATEGY = os.getenv("METABOLISM_STRATEGY", "LAZY")
# MAX_SINK_TIME: The absolute maximum age of an engram before the Gran Purge (30 days default).
MAX_SINK_TIME = int(os.getenv("MAX_SINK_TIME", str(30 * 24 * 3600)))

# EMOTIONAL CHROMA (v4.2.0)
DEFAULT_COLOR = "gray"
DEFAULT_EMOTION = "neutral"
# EMOTIONAL_DECAY_MULTIPLIERS (W2 — Calibration Rationale)
# Each multiplier adjusts the base EROSION_RATE for emotionally-tagged engrams.
# Values > 1.0 accelerate decay; values < 1.0 slow it (higher memory persistence).
#
# Theoretical basis (PIONEER mode — see ACE-CAL in utils/affect.py):
#   - orange (anxiety, 1.5x): High-arousal negative affect. Ebbinghaus (1885) and
#	 clinical anxiety research (DSM-5) show that anxiety states are highly
#	 context-sensitive — memories encoded under acute anxiety fade faster when the
#	 anxious context is resolved. Öhman & Mineka (2001) note salience is high but
#	 consolidation is fragile without repeated reinforcement.
#   - yellow (joy, 0.5x): Positive valence memories exhibit slower forgetting curves
#	 (Levenson, 1994 — positive affect promotes broader encoding). Joy-tagged
#	 engrams are reinforced by narrative recurrence and associated optimism bias.
#   - purple (ennui, 2.0x): Low arousal + negative valence = minimal consolidation
#	 signal. Izard's Differential Emotion Theory predicts ennui-tagged content has
#	 the lowest survival salience. Rapid erosion models cognitive 'clearing' of
#	 low-engagement states.
#   - cyan (envy/evolution, 0.8x): Moderate persistence. Forward-looking (growth)
#	 states encode with mild salience; erosion is slightly reduced to keep
#	 strategic evolution signals available for recall.
#   - blue (sadness, 1.0x): Standard decay. Sadness has moderate arousal and
#	 moderate consolidation per Warriner et al. (2013) / NRC VAD. No adjustment.
#   - gray (neutral, 1.0x): Baseline. Neutral content follows the raw EROSION_RATE
#	 without modification — the mathematical zero-point of the ACE.
#   - emerald (sovereignty, 0.7x): Strategic sovereignty-tagged engrams are
#	 intentionally persistent. They encode high-level architectural intent and
#	 identity directives, warranting a slower erosion rate to prevent drift.
#
# EMPIRICAL NOTE: These values are PIONEER mode defaults. ACADEMIC mode uses
# Warriner et al. (2013) / NRC VAD coordinates for Valence-Arousal, and CUSTOM
# mode allows per-emotion overrides via AFFECT_CUSTOM_OVERRIDES. A Monte Carlo
# simulation of decay trajectories across affect models is a tracked roadmap item
# (W2 → v6.0 ACE-CAL Research Build).
EMOTIONAL_DECAY_MULTIPLIERS = {
	"orange": 1.5,  # Anxiety: high arousal but fragile consolidation
	"yellow": 0.5,  # Joy: positive persistence (Levenson positive affect)
	"purple": 2.0,  # Ennui: lowest survival salience (Izard DET)
	"cyan": 0.8,  # Evolution: mild strategic persistence
	"blue": 1.0,  # Sadness: standard decay (Warriner VAD baseline)
	"gray": 1.0,  # Neutral: mathematical zero-point
	"emerald": 0.7,  # Sovereignty: intentional strategic persistence
}

# CHROMA-TONE MAPPING (v4.2.1)
# Mapping for non-technical narrative refraction.
CHROMA_TONE_MAPPING = {
	"orange": "Vigilant, alert, high risk-awareness, proactive warnings.",
	"yellow": "Optimistic, encouraging, success-focused, warm.",
	"purple": "Minimalist, extremely concise, efficiency-first, no fluff.",
	"cyan": "Visionary, future-oriented, focused on growth and backlog.",
	"blue": "Reflective, empathetic, serious, acknowledging weight.",
	"nostalgia": "Respectful, shared legacy focus, acknowledging the long road.",
	"gray": "Professional, balanced, direct, objective (Standard).",
	"emerald": "Sovereign, strategic, detached but loyal, focused on the architectural grand design.",
}

# ONTOLOGICAL INTEGRITY (v4.2.4)
CURRENT_SCHEMA_VERSION = 1

# DYNAMIC AGENTICS (v5.4.0)
DYNAMIC_EMOTION_SYNC = os.getenv("DYNAMIC_EMOTION_SYNC", "True").lower() == "true"
MULTI_EMOTION_INFERENCE = os.getenv("MULTI_EMOTION_INFERENCE", "True").lower() == "true"

IA_DIR = os.getenv("IA_DIR", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# SOVEREIGN PULSE (v6.0)
# Enables background rituals (Maintenance, Audit, Proactive Synthesis).
PULSE_ENABLED = os.getenv("PULSE_ENABLED", "True").lower() == "true"
# Pulse interval in seconds. Default: 3600 (1 hour).
PULSE_INTERVAL = int(os.getenv("PULSE_INTERVAL", "3600"))

# INTERACTION CADENCE (v5.4.0)
CADENCE_BURST_THRESHOLD = 30.0  # Seconds between prompts for 'Burst' mode (High Intensity)
CADENCE_ABSENCE_THRESHOLD = 86400 * 2  # 2 Days for 'Dormancy' greeting trigger
METABOLISM_STATE_FILE = os.path.join(IA_DIR, "storage", "metabolism_state.json")
# Overwrite legacy if needed
if os.getenv("METABOLISM_STATE_FILE"):
	METABOLISM_STATE_FILE = str(os.getenv("METABOLISM_STATE_FILE"))

# CLOUD VAULT (v5.4.1 / SEC-F02)
CLOUD_VAULT_ENABLED = os.getenv("CLOUD_VAULT_ENABLED", "False").lower() == "true"
CLOUD_VAULT_PROVIDER = os.getenv("CLOUD_VAULT_PROVIDER", "google_drive")
CLOUD_VAULT_FOLDER_ID = os.getenv("CLOUD_VAULT_FOLDER_ID", "")  # The GDrive Folder ID
CLOUD_SERVICE_ACCOUNT_FILE = os.getenv("CLOUD_SERVICE_ACCOUNT_FILE", os.path.join(IA_DIR, "storage", "keys", "service_account.json"))
CLOUD_VAULT_QUOTA_MB = int(os.getenv("CLOUD_VAULT_QUOTA_MB", "500"))
CLOUD_VAULT_RESERVE_COUNT = int(os.getenv("CLOUD_VAULT_RESERVE_COUNT", "4"))
# SEC-F02: GPG passphrase for AES-256 Soul Kit encryption. Read directly in vault.py.
# NOT cached here to avoid it appearing in repr(cfg) or debug logs.
# Set via CLOUD_VAULT_GPG_PASSPHRASE in .env (configured during install_neo.sh).
# EMOTIONAL CHROMA & ACE (v5.5.0 — ACE-CAL)
# AFFECT_MODEL: Select the calibration model for Valence/Arousal values.
#   - 'PIONEER': The original hand-curated values for the Red Pill Protocol.
#   - 'ACADEMIC': Values based on Warriner et al. (2013) / NRC VAD Lexicon.
#   - 'CUSTOM': Uses the JSON dict defined in AFFECT_CUSTOM_OVERRIDES.
AFFECT_MODEL = os.getenv("AFFECT_MODEL", "PIONEER").upper()

# AFFECT_CUSTOM_OVERRIDES: A JSON string to override specific emotion coordinates.
# E.g. AFFECT_CUSTOM_OVERRIDES='{"joy": [0.9, 0.9], "fear": [-1.0, 1.0]}'
AFFECT_CUSTOM_OVERRIDES = os.getenv("AFFECT_CUSTOM_OVERRIDES", "{}")

# SYNAPTIC FRAGMENTATION (v5.5.0 Patch — 'Anti-Amnesia' Chunking)
# Threshold: If memory > this length, it is split into multiple engrams.
CHUNK_THRESHOLD = int(os.getenv("CHUNK_THRESHOLD", "800"))
# Chunk Size: The target length for each engram fragment.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
# Chunk Overlap: The number of characters repeated between consecutive fragments.
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# SLEEP CYCLE REFINEMENT (v6.0)
# SLEEP_CHUNK_SIZE: Max characters per interaction fragment during sleep distillation.
SLEEP_CHUNK_SIZE = int(os.getenv("SLEEP_CHUNK_SIZE", "500"))
# SLEEP_CULL_THRESHOLD: Minimum intensity to keep a neutral chunk during consolidation.
SLEEP_CULL_THRESHOLD = float(os.getenv("SLEEP_CULL_THRESHOLD", "0.1"))
