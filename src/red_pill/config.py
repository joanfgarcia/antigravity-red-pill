"""
Red Pill Foundation — Configuration Layer (v6.2.0)

Cascade Order (lowest → highest priority):
	1. Foundation field defaults (baked into RedPillConfig)
	2. User .env file  (loaded via pydantic-settings)
	3. Enterprise read-only overrides (injected once at boot via set_enterprise_overrides)

Usage:
	import red_pill.config as cfg
	cfg.QDRANT_HOST          # module-level aliases (backward-compat)
	cfg.get_config()         # typed RedPillConfig instance
	cfg.set_enterprise_overrides({"CERBERUS_TOKEN": "..."})  # Enterprise boot
"""

from __future__ import annotations

import os
import shutil
import tempfile
import warnings
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve IA_DIR early (needed as env_file base path)
_IA_DIR = os.getenv(
	"IA_DIR",
	os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# Helper: detect container engine


def _detect_container_engine() -> str:
	if shutil.which("podman"):
		return "podman"
	if shutil.which("docker"):
		return "docker"
	return "podman"  # Bünker v6 default


# Helper: load affect multipliers from YAML


def _load_affect_multipliers(model_name: str) -> dict:
	try:
		current_dir = os.path.dirname(os.path.abspath(__file__))
		yml_path = os.path.join(current_dir, "data", "affect_models.yaml")
		with open(yml_path, "r", encoding="utf-8") as f:
			data = yaml.safe_load(f)
		return dict(data.get(model_name, data.get("PIONEER")).get("multipliers", {}))
	except Exception as e:
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


# RedPillConfig — the sovereign configuration model


class RedPillConfig(BaseSettings):
	"""
	Foundation configuration. All fields are injectable and Pydantic-validated.
	Enterprise/Community extend this by calling set_enterprise_overrides() at boot.
	"""

	model_config = SettingsConfigDict(
		env_file=os.path.join(_IA_DIR, ".env"),
		env_file_encoding="utf-8",
		extra="ignore",
		populate_by_name=True,
	)

	# -----------------------------------------------------------------------
	# PATHS
	# -----------------------------------------------------------------------
	IA_DIR: str = _IA_DIR

	@property
	def RUNTIME_DIR(self) -> str:
		"""OS-safe runtime directory for volatile state (LEDs, interaction timestamps)."""
		xdg = os.getenv("XDG_RUNTIME_DIR")
		if xdg and os.path.exists(xdg):
			return xdg

		# Fallback 1: Linux user runtime dir
		if os.name == "posix":
			uid_dir = f"/run/user/{os.getuid()}"
			if os.path.exists(uid_dir):
				return uid_dir

		# Fallback 2: System temp
		return tempfile.gettempdir()

	# -----------------------------------------------------------------------
	# LLM INFERENCE
	# -----------------------------------------------------------------------
	MLX_LM_URL: str = "http://127.0.0.1:8760/v1/chat/completions"

	# -----------------------------------------------------------------------
	# QDRANT (always local in Foundation)
	# -----------------------------------------------------------------------
	QDRANT_HOST: str = "localhost"
	QDRANT_PORT: int = 6333
	QDRANT_API_KEY: Optional[str] = None
	QDRANT_SCHEME: Optional[str] = None  # Auto-derived in validator

	@model_validator(mode="after")
	def _derive_qdrant_scheme(self) -> "RedPillConfig":
		if self.QDRANT_SCHEME is None:
			self.QDRANT_SCHEME = "http" if self.QDRANT_HOST in _LOCAL_HOSTS else "https"
		# SEC-F04: warn on cleartext remote Qdrant
		if self.QDRANT_SCHEME == "http" and self.QDRANT_HOST not in _LOCAL_HOSTS:
			warnings.warn(
				f"[SEC-F04] Qdrant is configured with scheme='http' on a non-local host "
				f"('{self.QDRANT_HOST}'). Engram data and API keys will be transmitted in "
				f"cleartext. Set QDRANT_SCHEME=https or restrict to localhost.",
				stacklevel=2,
			)
		return self

	@property
	def QDRANT_URL(self) -> str:
		return f"{self.QDRANT_SCHEME}://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

	# -----------------------------------------------------------------------
	# CONTAINER ENGINE
	# -----------------------------------------------------------------------
	CONTAINER_ENGINE: Optional[str] = None

	@model_validator(mode="after")
	def _detect_container(self) -> "RedPillConfig":
		if not self.CONTAINER_ENGINE:
			self.CONTAINER_ENGINE = _detect_container_engine()
		return self

	# -----------------------------------------------------------------------
	# MILVUS (Hive Mind)
	# -----------------------------------------------------------------------
	MILVUS_HOST: str = "localhost"
	MILVUS_PORT: int = 19530
	MILVUS_USER: str = ""
	MILVUS_PASSWORD: str = ""
	MILVUS_SECURE: Optional[bool] = None
	MILVUS_ENABLED: bool = False
	MILVUS_DB: str = "default"
	MILVUS_NLIST: int = 128
	MILVUS_LITE_ENABLED: bool = True
	MILVUS_LITE_PATH: str = os.path.join(_IA_DIR, "storage", "hive_lite.db")

	@model_validator(mode="after")
	def _derive_milvus_secure(self) -> "RedPillConfig":
		if self.MILVUS_SECURE is None:
			self.MILVUS_SECURE = self.MILVUS_HOST not in _LOCAL_HOSTS
		# SEC-F03: Force secure for remote
		if not self.MILVUS_SECURE and self.MILVUS_HOST not in _LOCAL_HOSTS:
			self.MILVUS_SECURE = True
		# SEC-002: warn on cleartext remote Milvus
		if self.MILVUS_ENABLED and not self.MILVUS_SECURE and self.MILVUS_HOST not in _LOCAL_HOSTS:
			warnings.warn(
				f"[SEC-002] HiveMind (Milvus) is configured with secure=False on a non-local host "
				f"('{self.MILVUS_HOST}'). Experience vectors will be transmitted in cleartext. "
				f"Set MILVUS_SECURE=True or restrict to localhost.",
				stacklevel=2,
			)
		return self

	# -----------------------------------------------------------------------
	# BRAIN & INFERENCE PROXY
	# -----------------------------------------------------------------------
	BRAIN_PATH: str = os.path.join(os.path.expanduser("~"), ".gemini/antigravity/brain")
	SIP_ENABLED: bool = True
	SIP_SOCKET_PATH: str = os.path.join(os.getenv("XDG_RUNTIME_DIR", "/tmp"), "red_pill_sip.sock")

	# -----------------------------------------------------------------------
	# MODELS & EMBEDDINGS
	# -----------------------------------------------------------------------
	EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
	VECTOR_SIZE: int = 384
	FASTEMBED_CACHE_PATH: str = os.path.join(_IA_DIR, "storage", "models")
	EXECUTION_PROVIDER: Optional[str] = None

	@model_validator(mode="after")
	def _setup_fastembed_cache(self) -> "RedPillConfig":
		os.makedirs(self.FASTEMBED_CACHE_PATH, exist_ok=True)
		os.environ["FASTEMBED_CACHE_PATH"] = self.FASTEMBED_CACHE_PATH
		return self

	# -----------------------------------------------------------------------
	# FLOW REGISTRY
	# -----------------------------------------------------------------------
	FLOW_REGISTRY_PATH: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "flow_registry.yaml")

	# -----------------------------------------------------------------------
	# B760 MEMORY DECAY
	# -----------------------------------------------------------------------
	DECAY_STRATEGY: str = "linear"
	EROSION_RATE: float = 0.01
	REINFORCEMENT_INCREMENT: float = 0.1
	PROPAGATION_FACTOR: float = 0.5
	IMMUNITY_THRESHOLD: float = 10.0
	PROPAGATION_DEPTH: int = 2
	PROPAGATION_DECAY: float = 0.5
	EMOTIONAL_SEED_FACTOR: float = 3.0
	MAX_PROPAGATION_POINTS: int = 20
	MAX_AXONS: int = 500

	@field_validator("DECAY_STRATEGY")
	@classmethod
	def _validate_decay_strategy(cls, v: str) -> str:
		if v not in ("linear", "exponential"):
			raise ValueError(f"Invalid DECAY_STRATEGY: {v}. Must be 'linear' or 'exponential'.")
		return v

	@field_validator("EROSION_RATE")
	@classmethod
	def _validate_erosion_rate(cls, v: float) -> float:
		if not (0 <= v <= 1.0):
			raise ValueError(f"EROSION_RATE must be between 0 and 1: {v}")
		return v

	@field_validator("PROPAGATION_FACTOR")
	@classmethod
	def _validate_propagation_factor(cls, v: float) -> float:
		if not (0 <= v <= 1.0):
			raise ValueError(f"PROPAGATION_FACTOR must be between 0 and 1: {v}")
		return v

	# -----------------------------------------------------------------------
	# LOGGING & AGENT IDENTITY
	# -----------------------------------------------------------------------
	LOG_LEVEL: str = "INFO"
	AGENT_NAME: str = "Agente"
	OPERATOR_DISPLAY_NAME: str = os.getenv("USER_NAME", os.getenv("USER", "Operador"))

	# -----------------------------------------------------------------------
	# SWARM CONFIG
	# -----------------------------------------------------------------------
	SWARM_TELEMETRY_DEFAULT: str = "NONE"  # NONE, MINIMUM, FULL

	# -----------------------------------------------------------------------
	# NOTIFICATIONS
	# -----------------------------------------------------------------------
	NOTIFICATIONS_ENABLED: bool = True
	NOTIFICATION_SOUND: bool = False

	# -----------------------------------------------------------------------
	# DEEP RECALL TRIGGERS
	# -----------------------------------------------------------------------
	DEEP_RECALL_TRIGGERS: List[str] = []

	@model_validator(mode="after")
	def _build_deep_recall_triggers(self) -> "RedPillConfig":
		_default = "don't you remember,¿no te acuerdas?,deep recall,do you really not remember?,esfuerzate en recordar,try hard!"
		_env_raw = os.getenv("DEEP_RECALL_TRIGGERS", _default)
		base = ["despierta", "despierta neo", "wake up"]
		extras = [t.strip().lower() for t in _env_raw.split(",") if t.strip()]
		self.DEEP_RECALL_TRIGGERS = base + extras
		return self

	# -----------------------------------------------------------------------
	# METABOLISM
	# -----------------------------------------------------------------------
	METABOLISM_ENABLED: bool = True
	METABOLISM_COOLDOWN: int = 3600
	METABOLISM_AUTO_COLLECTIONS: List[str] = ["work_memories", "social_memories", "story_memories"]
	METABOLISM_STATE_FILE: str = os.path.join(_IA_DIR, "storage", "metabolism_state.json")
	ABSENCE_THRESHOLD: int = 7 * 24 * 3600
	ABSENCE_GUARD_SCROLL_LIMIT: int = 500
	METABOLISM_STRATEGY: str = "LAZY"
	MAX_SINK_TIME: int = 30 * 24 * 3600

	@field_validator("METABOLISM_AUTO_COLLECTIONS", mode="before")
	@classmethod
	def _parse_collections(cls, v: Any) -> Any:
		if isinstance(v, str):
			return [c.strip() for c in v.split(",") if c.strip()]
		return v

	# -----------------------------------------------------------------------
	# AFFECT / EMOTIONAL
	# -----------------------------------------------------------------------
	DEFAULT_COLOR: str = "gray"
	DEFAULT_EMOTION: str = "neutral"
	AFFECT_DECAY_MODEL: str = "PIONEER"
	AFFECT_MODEL: str = "PIONEER"
	AFFECT_CUSTOM_OVERRIDES: str = "{}"
	DYNAMIC_EMOTION_SYNC: bool = True
	MULTI_EMOTION_INFERENCE: bool = True

	# -----------------------------------------------------------------------
	# NEURO-AGENTIC TUNING
	# -----------------------------------------------------------------------
	SEMANTIC_INTENT_THRESHOLD_STR: str = "Low"

	@property
	def SEMANTIC_INTENT_THRESHOLD(self) -> float:
		return 0.75 if self.SEMANTIC_INTENT_THRESHOLD_STR.upper() == "HIGH" else 0.5

	# Re-map env var name
	model_config = SettingsConfigDict(
		env_file=os.path.join(_IA_DIR, ".env"),
		env_file_encoding="utf-8",
		extra="ignore",
		populate_by_name=True,
	)

	# -----------------------------------------------------------------------
	# MCP INTERCEPTOR
	# -----------------------------------------------------------------------
	INTERCEPTOR_ENABLED: bool = False
	INTERCEPTOR_RAG_ENABLED: bool = True
	INTERCEPTOR_CIRCUIT_BREAKER_ENABLED: bool = False

	# -----------------------------------------------------------------------
	# FERRARI PROTOCOL — Emotional Intelligence Plugins
	# -----------------------------------------------------------------------
	COGNITIVE_ROUTER_ENABLED: bool = True  # Plugin 05: task routing by operator color
	TONE_ADAPTER_ENABLED: bool = True  # Plugin 06: verbal tone adaptation
	MOOD_ANALYTICS_ENABLED: bool = True  # Plugin 07: longitudinal mood trend analysis
	EMOTIVE_RECALL_ENABLED: bool = True  # Plugin 08: RAG recall by emotional resonance
	PROACTIVE_SIGNAL_ENABLED: bool = True  # Plugin 09: sustained critical state alerts
	PROACTIVE_SIGNAL_RED_THRESHOLD: int = 5  # Consecutive RED memories before pain signal
	PREDICTIVE_PRELOAD_ENABLED: bool = True  # Plugin 10: predictive context preloading

	# -----------------------------------------------------------------------
	# SOVEREIGN PULSE
	# -----------------------------------------------------------------------
	PULSE_ENABLED: bool = True
	PULSE_INTERVAL: int = 3600

	# -----------------------------------------------------------------------
	# INTERACTION CADENCE
	# -----------------------------------------------------------------------
	CADENCE_BURST_THRESHOLD: float = 30.0
	CADENCE_ABSENCE_THRESHOLD: int = 86400 * 2

	# -----------------------------------------------------------------------
	# LAZARUS SYNC
	# -----------------------------------------------------------------------
	LAZARUS_SYNC_ENABLED: bool = True
	LAZARUS_SYNC_INTERVAL: int = 300
	LAZARUS_STATE_FILE: str = os.path.join(_IA_DIR, "storage", "lazarus_state.json")

	# -----------------------------------------------------------------------
	# SEMANTIC RESONANCE
	# -----------------------------------------------------------------------
	RESONANCE_ENABLED: bool = True
	RESONANCE_THRESHOLD: float = 0.4
	RESONANCE_INTERVAL: int = 600

	# -----------------------------------------------------------------------
	# CLOUD VAULT
	# -----------------------------------------------------------------------
	CLOUD_VAULT_ENABLED: bool = False
	CLOUD_VAULT_PROVIDER: str = "google_drive"
	CLOUD_VAULT_FOLDER_ID: str = ""
	CLOUD_SERVICE_ACCOUNT_FILE: str = os.path.join(_IA_DIR, "storage", "keys", "service_account.json")
	CLOUD_VAULT_QUOTA_MB: int = 500
	CLOUD_VAULT_RESERVE_COUNT: int = 4

	# -----------------------------------------------------------------------
	# SYNAPTIC FRAGMENTATION
	# -----------------------------------------------------------------------
	CHUNK_THRESHOLD: int = 800
	CHUNK_SIZE: int = 500
	CHUNK_OVERLAP: int = 100

	# -----------------------------------------------------------------------
	# SLEEP CYCLE
	# -----------------------------------------------------------------------
	SLEEP_CHUNK_SIZE: int = 500
	SLEEP_CULL_THRESHOLD: float = 0.1

	# Sleep Cycle Plugin flags — each ritual individually activatable
	SLEEP_PLUGIN_USP: bool = True  # Operator Mood Profile refresh
	SLEEP_PLUGIN_DREAM: bool = True  # Oneiromancy (latent semantic association)
	SLEEP_PLUGIN_CONSOLIDATION: bool = True  # Memory consolidation (lazy sleep)
	SLEEP_PLUGIN_CHRONICLE: bool = False  # Ariadne's Thread + MCP archive search
	# └─ CHRONICLE=False by default: requires antigravity decrypt→ingest pipeline.
	#   Also gates archive_memories in MCP search_memory_research.
	#   Agent can auto-activate when archive_memories has content.

	# BE_WATER: Agent auto-sizes payload limit based on available VRAM.
	# Override with MAX_PAYLOAD_CHARS=<int> in .env to force a specific limit.
	MAX_PAYLOAD_CHARS: Optional[int] = None

	@model_validator(mode="after")
	def _be_water_payload_limit(self) -> "RedPillConfig":
		"""Automatically adapt max payload size to available VRAM (BE_WATER protocol)."""
		if self.MAX_PAYLOAD_CHARS is not None:
			return self  # User override takes precedence
		try:
			import torch

			vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
			if vram_gb < 4:
				self.MAX_PAYLOAD_CHARS = 1_000
			elif vram_gb < 8:
				self.MAX_PAYLOAD_CHARS = 5_000
			# > 8 GB: no limit (None)
		except Exception:
			pass  # CPU or torch unavailable: no limit applied
		return self

	# -----------------------------------------------------------------------
	# BAYESIAN MEMORY
	# -----------------------------------------------------------------------
	BAYESIAN_STABILITY_KAPPA: float = 0.05
	BAYESIAN_REINFORCEMENT_GAIN: float = 1.0

	# -----------------------------------------------------------------------
	# NEURO-IMMUNE SIGNALS
	# -----------------------------------------------------------------------
	SIGNAL_VISIBILITY_THRESHOLD: float = 5.0
	SIGNAL_BASE_NOTIFICATION: float = 5.0
	SIGNAL_BASE_PAIN_CUDA: float = 7.0
	SIGNAL_PAIN_ESCALATION_RATE: float = 0.5
	SIGNAL_AMNESIA_HOURS: int = 4
	SIGNAL_MIGRAINE_VECTORS: int = 10000

	# -----------------------------------------------------------------------
	# ENTERPRISE EXTENSION (read-only after init — set by Enterprise at boot)
	# -----------------------------------------------------------------------
	_enterprise_overrides: Dict[str, Any] = {}

	def get_enterprise(self, key: str, default: Any = None) -> Any:
		"""Read a value from the Enterprise override layer."""
		return self._enterprise_overrides.get(key, default)


# Static data (not env-driven)

BAYESIAN_COLLECTIONS: List[str] = ["skill_memories", "work_memories", "directive_memories", "archive_memories"]

PERMANENT_COLLECTIONS: List[str] = ["archive_memories", "directive_memories"]

MEMORY_ENGINES: Dict[str, str] = {
	"work_memories": "bayesian",
	"skill_memories": "bayesian",
	"directive_memories": "bayesian",
	"archive_memories": "bayesian",
	"social_memories": "fsrs_real",
	"story_memories": "fsrs_real",
}

CHROMA_TONE_MAPPING: Dict[str, str] = {
	"orange": "Vigilant, alert, high risk-awareness, proactive warnings.",
	"yellow": "Optimistic, encouraging, success-focused, warm.",
	"purple": "Minimalist, extremely concise, efficiency-first, no fluff.",
	"cyan": "Visionary, future-oriented, focused on growth and backlog.",
	"blue": "Reflective, empathetic, serious, acknowledging weight.",
	"nostalgia": "Respectful, shared legacy focus, acknowledging the long road.",
	"gray": "Professional, balanced, direct, objective (Standard).",
	"emerald": "Sovereign, strategic, detached but loyal, focused on the architectural grand design.",
}

CURRENT_SCHEMA_VERSION: int = 1

# Singleton config loader

_enterprise_overrides_store: Dict[str, Any] = {}


@lru_cache(maxsize=1)
def get_config() -> RedPillConfig:
	"""Return the singleton RedPillConfig instance."""
	return RedPillConfig()


def set_enterprise_overrides(overrides: Dict[str, Any]) -> None:
	"""
	Enterprise/Community hook: inject read-only config overrides at boot.
	Safe to call before or after get_config() — syncs to both the store
	and the live singleton instance if it already exists.
	"""
	_enterprise_overrides_store.update(overrides)
	# Also sync to the live singleton if it's already cached
	try:
		cfg = get_config()
		cfg._enterprise_overrides.update(overrides)
	except Exception:
		# Singleton not yet created — the store will be read at first get_config()
		get_config.cache_clear()


# Module-level aliases — backward compatibility (do NOT remove)
# All existing code does: import red_pill.config as cfg; cfg.QDRANT_HOST


def _cfg() -> RedPillConfig:
	"""Lazy accessor — deferred until first module-level alias is touched."""
	return get_config()


# Paths
IA_DIR = _IA_DIR

# LLM
# filled below after first import via __getattr__

# We use a lazy-init pattern via __getattr__ to avoid circular imports
# and to allow tests to monkeypatch individual settings cleanly.


def __getattr__(name: str) -> Any:
	"""
	Module-level __getattr__: resolves any attribute access on this module
	by delegating to the RedPillConfig singleton.
	This replaces the old 60+ global variables with a single lazy dispatch.
	"""
	cfg = get_config()
	# Special computed properties
	if name == "QDRANT_URL":
		return cfg.QDRANT_URL
	if name == "SEMANTIC_INTENT_THRESHOLD":
		return cfg.SEMANTIC_INTENT_THRESHOLD
	if name == "EMOTIONAL_DECAY_MULTIPLIERS":
		return _load_affect_multipliers(cfg.AFFECT_DECAY_MODEL)
	# Static mappings (not on the model)
	if name == "BAYESIAN_COLLECTIONS":
		return BAYESIAN_COLLECTIONS
	if name == "PERMANENT_COLLECTIONS":
		return PERMANENT_COLLECTIONS
	if name == "MEMORY_ENGINES":
		return MEMORY_ENGINES
	if name == "CHROMA_TONE_MAPPING":
		return CHROMA_TONE_MAPPING
	if name == "CURRENT_SCHEMA_VERSION":
		return CURRENT_SCHEMA_VERSION
	# Delegate to model field
	try:
		return getattr(cfg, name)
	except AttributeError:
		raise AttributeError(f"module 'red_pill.config' has no attribute '{name}'")
