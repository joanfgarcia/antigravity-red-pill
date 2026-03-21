import os

from dotenv import load_dotenv

# CORE PATHS (v6.1.0)
IA_DIR = os.getenv("IA_DIR", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Ensure explicit .env loading for absolute paths (fixes MCP external execution context)
env_path = os.path.join(IA_DIR, ".env")
load_dotenv(env_path)

# SEC-F05: CUDA Configuration.
# Re-enabled (v6.0.0). Automated LD_LIBRARY_PATH injection for cuDNN 9 support.
if "CUDA_VISIBLE_DEVICES" not in os.environ:
	pass

MLX_LM_URL = os.getenv("MLX_LM_URL", "http://127.0.0.1:8080/v1/chat/completions")

# CUDA Configuration (v6.0.0) - Removed runtime LD_LIBRARY_PATH injection
# as it breaks PyTorch 2.10 `libc10_cuda.so` initialization by forcing older Ollama libs.
if "CUDA_VISIBLE_DEVICES" not in os.environ:
	pass

# QDRANT
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
_local_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
QDRANT_SCHEME = os.getenv("QDRANT_SCHEME", "http" if QDRANT_HOST in _local_hosts else "https")
QDRANT_URL = f"{QDRANT_SCHEME}://{QDRANT_HOST}:{QDRANT_PORT}"

# CONTAINER_ENGINE abstraction (v6.1.0)
# Read from .env, fallback to path-based detection (heuristics).
CONTAINER_ENGINE = os.getenv("CONTAINER_ENGINE", None)
if not CONTAINER_ENGINE:
	import shutil

	if shutil.which("podman"):
		CONTAINER_ENGINE = "podman"
	elif shutil.which("docker"):
		CONTAINER_ENGINE = "docker"
	else:
		CONTAINER_ENGINE = "podman"  # Standard default for Bünker v6

# SEC-F04: Warn when Qdrant is reachable over an unencrypted non-local connection.
# Remote http:// exposes API key and engram content to any network observer.
# Remote http:// exposes API key and engram content to any network observer.
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
MILVUS_SECURE = os.getenv("MILVUS_SECURE", "False" if MILVUS_HOST in _local_hosts else "True").lower() == "true"
if not MILVUS_SECURE and MILVUS_HOST not in _local_hosts:
	MILVUS_SECURE = True  # SEC-F03: Force secure connection for remote hosts
MILVUS_ENABLED = os.getenv("MILVUS_ENABLED", "False").lower() == "true"
MILVUS_DB = os.getenv("MILVUS_DB", "default")
MILVUS_NLIST = int(os.getenv("MILVUS_NLIST", "128"))
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


# SENSOR & BRAIN CONFIG
BRAIN_PATH = os.getenv("BRAIN_PATH", os.path.join(os.path.expanduser("~"), ".gemini/antigravity/brain"))
# SOVEREIGN INFERENCE PROXY (SIP)
_run_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")
SIP_ENABLED = os.getenv("SIP_ENABLED", "True").lower() == "true"
SIP_SOCKET_PATH = os.getenv("SIP_SOCKET_PATH", os.path.join(_run_dir, "red_pill_sip.sock"))

# MODELS
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "384"))

# FASTEMBED Cache Persistence (v6.1.0)
_default_cache = os.path.join(IA_DIR, "storage", "models")
FASTEMBED_CACHE_PATH = os.getenv("FASTEMBED_CACHE_PATH", _default_cache)
os.makedirs(FASTEMBED_CACHE_PATH, exist_ok=True)
os.environ["FASTEMBED_CACHE_PATH"] = FASTEMBED_CACHE_PATH

# FLOW REGISTRY (v6.1.0)
FLOW_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "flow_registry.yaml")

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

# AGENT (Dynamic Identity)
AGENT_NAME = os.getenv("AGENT_NAME", "Agente")

# OPERATOR (SEC-002: replaces hardcoded display names like 'Joan' in notifications)
# Set via USER_NAME in .env, fallback to OS username, fallback to 'Operador'
OPERATOR_DISPLAY_NAME = os.getenv("USER_NAME", os.getenv("USER", "Operador"))

# SWARM CONFIG
SWARM_TELEMETRY_DEFAULT = os.getenv("SWARM_TELEMETRY_DEFAULT", "NONE")  # NONE, MINIMUM, FULL

# NOTIFICATIONS
# Set to 'False' to silence the system entirely
NOTIFICATIONS_ENABLED = os.getenv("NOTIFICATIONS_ENABLED", "True").lower() == "true"
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

# AFFECT DECAY MODELS (v6.1.0)
# NOTE: The resulting decay curves from these models are neuro-symbolic design choices
# regarding AI psychological safety and longitudinal alignment. They are NOT empirical models
# of human biological memory (where trauma/anxiety often persist instead of decaying).
# See docs/PHILOSOPHY.md for documentation of these Sovereign Trade-offs.
DEFAULT_COLOR = "gray"
DEFAULT_EMOTION = "neutral"
AFFECT_DECAY_MODEL = os.getenv("AFFECT_DECAY_MODEL", "PIONEER")


def _load_affect_multipliers(model_name: str) -> dict:
	try:
		import yaml

		# Calculate path relative to this source file, not IA_DIR (which tests monkeypatch)
		current_dir = os.path.dirname(os.path.abspath(__file__))
		yml_path = os.path.join(current_dir, "data", "affect_models.yaml")
		with open(yml_path, "r", encoding="utf-8") as f:
			data = yaml.safe_load(f)
		return dict(data.get(model_name, data.get("PIONEER")).get("multipliers", {}))
	except Exception as e:
		import warnings

		warnings.warn(f"Failed to load affect_models.yaml: {e}. Falling back to default PIONEER profile.")
		return {
			"orange": 1.5,
			"yellow": 0.5,
			"purple": 2.0,
			"cyan": 0.8,
			"blue": 1.0,
			"gray": 1.0,
			"emerald": 0.7,
		}


EMOTIONAL_DECAY_MULTIPLIERS = _load_affect_multipliers(AFFECT_DECAY_MODEL)

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

# NEURO-AGENTIC TUNING (v6.1.0)
_semantic_str = os.getenv("SEMANTIC_INTENT_THRESHOLD", "Low").upper()
SEMANTIC_INTENT_THRESHOLD = 0.75 if _semantic_str == "HIGH" else 0.5

# MCP Interceptor
INTERCEPTOR_ENABLED = str(os.getenv("INTERCEPTOR_ENABLED", "False")).lower() in ("true", "1", "yes")
INTERCEPTOR_RAG_ENABLED = str(os.getenv("INTERCEPTOR_RAG_ENABLED", "True")).lower() in ("true", "1", "yes")
INTERCEPTOR_CIRCUIT_BREAKER_ENABLED = str(os.getenv("INTERCEPTOR_CIRCUIT_BREAKER_ENABLED", "False")).lower() in ("true", "1", "yes")

# SOVEREIGN PULSE (v6.0)
# Enables background rituals (Maintenance, Audit, Proactive Synthesis).
PULSE_ENABLED = os.getenv("PULSE_ENABLED", "True").lower() == "true"
# Pulse interval in seconds. Default: 3600 (1 hour).
PULSE_INTERVAL = int(os.getenv("PULSE_INTERVAL", "3600"))

# INTERACTION CADENCE (v5.4.0)
CADENCE_BURST_THRESHOLD = 30.0  # Seconds between prompts for 'Burst' mode (High Intensity)
CADENCE_ABSENCE_THRESHOLD = 86400 * 2  # 2 Days for 'Dormancy' greeting trigger
METABOLISM_STATE_FILE = os.path.join(IA_DIR, "storage", "metabolism_state.json")

# LAZARUS SYNC (v6.0 - Phase 6)
LAZARUS_SYNC_ENABLED = os.getenv("LAZARUS_SYNC_ENABLED", "True").lower() == "true"
LAZARUS_SYNC_INTERVAL = int(os.getenv("LAZARUS_SYNC_INTERVAL", "300"))  # Default: 5 minutes
LAZARUS_STATE_FILE = os.path.join(IA_DIR, "storage", "lazarus_state.json")

# SEMANTIC RESONANCE (v6.0 - Phase 7)
RESONANCE_ENABLED = os.getenv("RESONANCE_ENABLED", "True").lower() == "true"
RESONANCE_THRESHOLD = float(os.getenv("RESONANCE_THRESHOLD", "0.4"))  # Similarity distance threshold
RESONANCE_INTERVAL = int(os.getenv("RESONANCE_INTERVAL", "600"))  # Polling interval
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

# BAYESIAN MEMORY (v6.1 Phase B.1)
BAYESIAN_COLLECTIONS = ["skill_memories", "work_memories", "directive_memories"]

# Provide a mapping of collections to their primary memory engine plugin
MEMORY_ENGINES = {
	"work_memories": "bayesian",
	"skill_memories": "bayesian",
	"directive_memories": "bayesian",
	"social_memories": "fsrs_real",
	"story_memories": "fsrs_real",
}
# BAYESIAN_STABILITY_KAPPA: Rate of uncertainty accumulation (beta) per day.
# Higher = faster "forgetting" of technical utility.
BAYESIAN_STABILITY_KAPPA = float(os.getenv("BAYESIAN_STABILITY_KAPPA", "0.05"))
# BAYESIAN_REINFORCEMENT_GAIN: Amount of alpha added per successful recall.
BAYESIAN_REINFORCEMENT_GAIN = float(os.getenv("BAYESIAN_REINFORCEMENT_GAIN", "1.0"))

# NEURO-IMMUNE SENSITIVITY (BIOLOGICAL DASHBOARD v6.1)
# Threshold for a signal to be visible in the prompt context
SIGNAL_VISIBILITY_THRESHOLD = float(os.getenv("SIGNAL_VISIBILITY_THRESHOLD", "5.0"))
# Base intensity for normal notifications (decays automatically on read)
SIGNAL_BASE_NOTIFICATION = float(os.getenv("SIGNAL_BASE_NOTIFICATION", "5.0"))
# Base intensity for a CUDA failure pain signal
SIGNAL_BASE_PAIN_CUDA = float(os.getenv("SIGNAL_BASE_PAIN_CUDA", "7.0"))
# Escalation rate per pulse for untreated pain signals
SIGNAL_PAIN_ESCALATION_RATE = float(os.getenv("SIGNAL_PAIN_ESCALATION_RATE", "0.5"))
# Thresholds for Amygdala/Autonomic alerts
SIGNAL_AMNESIA_HOURS = int(os.getenv("SIGNAL_AMNESIA_HOURS", "4"))
SIGNAL_MIGRAINE_VECTORS = int(os.getenv("SIGNAL_MIGRAINE_VECTORS", "10000"))
