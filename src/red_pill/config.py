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
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from red_pill.core.paths import get_config_dir, get_db_dir, get_models_dir, get_state_dir, migrate_legacy_xdg_config

migrate_legacy_xdg_config()


# Resolve paths early for execution isolation (Agentic Self-Assembly)
_APP_ROOT = os.getenv("APP_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_WORKSPACE_ROOT = os.path.expanduser(os.getenv("WORKSPACE_ROOT", os.path.dirname(_APP_ROOT)))

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


# BridgeTarget — one step in an execution-bridge fallback cascade


class BridgeTarget(BaseModel):
	"""One step in an execution-bridge fallback cascade (Telegram/inbox worker).

	The cascade is tried in order; the first target whose prompt() succeeds wins.
	`model`/`effort` are per-target (e.g. claude/opus/high → agy/pro/medium →
	local/samantha). `effort` speaks the portable STANDARD_EFFORTS scale; each
	bridge maps it to its own control (claude → --effort, agy → model "(Mode)",
	local → ignored).
	"""

	backend: Literal["agy", "claude", "opencode", "local"]
	model: Optional[str] = None
	effort: Optional[Literal["low", "medium", "high"]] = None
	server_url: Optional[str] = None  # opencode only: http://localhost:PORT for --attach (None → direct/cold)


# RedPillConfig — the sovereign configuration model


class RedPillConfig(BaseSettings):
	"""
	Foundation configuration. All fields are injectable and Pydantic-validated.
	Enterprise/Community extend this by calling set_enterprise_overrides() at boot.
	"""

	model_config = SettingsConfigDict(
		env_file=os.path.join(get_config_dir(), ".env"),
		env_file_encoding="utf-8",
		extra="ignore",
		populate_by_name=True,
	)

	# -----------------------------------------------------------------------
	# PATHS & PROFILES (Agentic Self-Assembly)
	# -----------------------------------------------------------------------
	WORKSPACE_ROOT: str = _WORKSPACE_ROOT
	APP_ROOT: str = _APP_ROOT
	RED_PILL_PROFILE: str = "user"
	AGENT_CORE_DIR: str = os.path.join(_WORKSPACE_ROOT, "Agent_Core")
	# USER_ATLAS_DIR removed: the atlas is per-project now (workspaces.yaml / discovered via .agent).
	# AGENT_CORE_DIR's effective source for anchors is workspaces.yaml:agent_core
	# (see scripts/_config_common.agent_core_vars). Default here is relative for back-compat.

	@field_validator("WORKSPACE_ROOT", mode="before")
	@classmethod
	def _expand_workspace_root(cls, v: str) -> str:
		return os.path.expanduser(v)

	@field_validator("AGENT_CORE_DIR", mode="before")
	@classmethod
	def _expand_agent_core_dir(cls, v: str) -> str:
		return os.path.expanduser(v)

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
	# COGNITIVE DYNAMICS
	# -----------------------------------------------------------------------
	ABSOLUTE_KEYWORDS: List[str] = ["Aleth", "Bünker", "770", "enter-pánico", "PAAAAARAAAAAA", "engrama", "skin", "Titanium", "Joan"]
	CONTEXT_HYDRATION_DEPTH: str = "HIGH"
	EMERGENCY_CLOUD_OVERRIDE: bool = False

	# -----------------------------------------------------------------------
	# IDENTITY DEPTH (per-channel)
	# Values: "full" | "medium" | "low"
	# -----------------------------------------------------------------------
	IDENTITY_DEPTH_IDE: str = "full"
	IDENTITY_DEPTH_NEON_LINK: str = "medium"
	IDENTITY_DEPTH_HEADLESS: str = "low"

	@field_validator("CONTEXT_HYDRATION_DEPTH", mode="before")
	@classmethod
	def _normalize_hydration_depth(cls, v: Any) -> str:
		if isinstance(v, str):
			return v.strip().upper()
		return "HIGH"

	@field_validator("IDENTITY_DEPTH_IDE", "IDENTITY_DEPTH_NEON_LINK", "IDENTITY_DEPTH_HEADLESS", mode="before")
	@classmethod
	def _normalize_identity_depth(cls, v: Any) -> str:
		_valid = {"full", "medium", "low"}
		if isinstance(v, str):
			normalized = v.strip().lower()
			if normalized in _valid:
				return normalized
		return "medium"

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
		if self.QDRANT_HOST == ":memory:":
			return ":memory:"
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
	MILVUS_LITE_PATH: str = str(get_db_dir() / "hive_lite.db")

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
	SIP_SOCKET_PATH: str = os.path.join(os.getenv("XDG_RUNTIME_DIR", "/tmp"), "red-pill", "red_pill.sock")

	# -----------------------------------------------------------------------
	# MODELS & EMBEDDINGS
	# -----------------------------------------------------------------------
	# Multilingual (Spanish/English) 384-dim model. Same vector size as the old
	# all-MiniLM-L6-v2 (English-only) → no collection schema migration, but the
	# stored vectors must be recomputed (scripts/reembed_collections.py).
	EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
	VECTOR_SIZE: int = 384
	FASTEMBED_CACHE_PATH: str = str(get_models_dir())
	EMBEDDING_LOCAL_FILES_ONLY: bool = True
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
	# ICE Mode enforces local zero-trust encryption via pure-mls for the MinionInbox.
	# When False, the system defaults to WATER mode (O(1) raw SQLite speed).
	ICE_MODE_ENABLED: bool = False
	NEON_LINK_ENABLED: bool = True
	NEON_LINK_URL: str = "http://localhost:8770"
	# neon-link releases up to 0.5.1 ship the FastAPI app (GET /health, /inbox/summary)
	# but never serve it (no uvicorn caller in the daemon), so probing NEON_LINK_URL yields
	# permanent false positives (neon_hung severity 10 + heal restarts, doctor RED).
	# Flip to True only when the deployed neon-link actually binds the HTTP API.
	NEON_LINK_HTTP_API: bool = False
	# Defense-in-depth for P2P sync: only apply incoming sync payloads whose inbox originator
	# is a known peer (peers.json). Sync flows into cognitive_tasks and can be executed
	# autonomously, so fail closed by default — an unknown/absent originator is rejected.
	P2P_SYNC_REQUIRE_KNOWN_PEER: bool = True

	# -----------------------------------------------------------------------
	# ANTIGRAVITY IDE BRIDGE
	# -----------------------------------------------------------------------
	IDE_BACKEND: str = "auto"  # "agy" | "grpc" | "claude" | "local" | "auto"
	# Gate autonomous Flash-consuming operations (cognitive queue, minion
	# auto-inject, entropy executor). Telegram inbox processing is NOT
	# affected — only background/autonomous agy prompts are suppressed.
	AUTONOMOUS_AGY_ENABLED: bool = False
	# Ordered fallback cascade for inbox/Telegram execution. Empty (default) →
	# single bridge via IDE_BACKEND (back-compat, no behaviour change). When set,
	# the worker tries each target in order and uses the first with quota; if all
	# fail, the pertinent error is surfaced to the user. JSON-encoded in .env, e.g.
	# TELEGRAM_BRIDGE_CASCADE='[{"backend":"claude","model":"opus","effort":"high"}]'
	TELEGRAM_BRIDGE_CASCADE: List[BridgeTarget] = []
	AWAKENING_BRIDGE_CASCADE: List[BridgeTarget] = []
	DEFAULT_MINION_BRIDGE_CASCADE: List[BridgeTarget] = []

	@field_validator("TELEGRAM_BRIDGE_CASCADE", "AWAKENING_BRIDGE_CASCADE", "DEFAULT_MINION_BRIDGE_CASCADE", mode="before")
	@classmethod
	def _parse_bridge_cascades(cls, v: Any) -> Any:
		if isinstance(v, str):
			import json

			try:
				return json.loads(v)
			except Exception as e:
				raise ValueError(f"Failed to parse JSON for bridge cascade: {e}")
		return v

	@field_validator("IDE_BACKEND")
	@classmethod
	def _validate_ide_backend(cls, v: str) -> str:
		v = v.strip().lower()
		if v not in ("agy", "grpc", "claude", "local", "auto"):
			raise ValueError(f"IDE_BACKEND must be 'agy', 'grpc', 'claude', 'local', or 'auto': {v}")
		return v

	# -----------------------------------------------------------------------
	# NOTIFICATIONS
	# -----------------------------------------------------------------------
	NOTIFICATIONS_ENABLED: bool = True
	NOTIFICATION_SOUND: bool = False

	# -----------------------------------------------------------------------
	# REACTIVE DEBOUNCE (Telegram sliding window prompt accumulation)
	# -----------------------------------------------------------------------
	REACTIVE_DEBOUNCE_ENABLED: bool = False
	REACTIVE_DEBOUNCE_SECONDS: int = 5

	# -----------------------------------------------------------------------
	# DEEP RECALL TRIGGERS
	# -----------------------------------------------------------------------
	DEEP_RECALL_TRIGGERS: Any = []

	@field_validator("DEEP_RECALL_TRIGGERS", mode="before")
	@classmethod
	def _parse_deep_recall_triggers(cls, v: Any) -> Any:
		if isinstance(v, str):
			return [t.strip() for t in v.split(",") if t.strip()]
		return v

	@model_validator(mode="after")
	def _build_deep_recall_triggers(self) -> "RedPillConfig":
		base = ["despierta", "despierta neo", "wake up"]
		if self.DEEP_RECALL_TRIGGERS:
			extras = [t.strip().lower() for t in self.DEEP_RECALL_TRIGGERS if t.strip()]
		else:
			_default = "don't you remember,¿no te acuerdas?,deep recall,do you really not remember?,esfuerzate en recordar,try hard!"
			_env_raw = os.getenv("DEEP_RECALL_TRIGGERS", _default)
			extras = [t.strip().lower() for t in _env_raw.split(",") if t.strip()]
		self.DEEP_RECALL_TRIGGERS = base + extras
		return self

	# -----------------------------------------------------------------------
	# METABOLISM
	# -----------------------------------------------------------------------
	METABOLISM_ENABLED: bool = True
	METABOLISM_COOLDOWN: int = 3600
	METABOLISM_AUTO_COLLECTIONS: Any = ["work_memories", "social_memories", "story_memories"]
	CHRONICLE_PLUGINS: List[str] = ["antigravity", "claude_code"]

	@field_validator("CHRONICLE_PLUGINS", mode="before")
	@classmethod
	def _parse_chronicle_plugins(cls, v: Any) -> Any:
		if isinstance(v, str):
			import json

			try:
				return json.loads(v)
			except Exception:
				return [p.strip() for p in v.split(",") if p.strip()]
		return v

	METABOLISM_STATE_FILE: str = str(get_state_dir() / "metabolism_state.json")
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
	# Dynamic Gravity Point: HEDONIC_SET_POINT_COLOR is read from XDG config at boot.
	# This serves as the fallback if no config is yet present.
	HEDONIC_SET_POINT_COLOR: str = "emerald"
	OVERNIGHT_THERAPY_THRESHOLD_HOURS: int = 4

	# -----------------------------------------------------------------------
	# NEURO-AGENTIC TUNING
	# -----------------------------------------------------------------------
	SEMANTIC_INTENT_THRESHOLD_STR: str = "Low"

	@property
	def SEMANTIC_INTENT_THRESHOLD(self) -> float:
		return 0.75 if self.SEMANTIC_INTENT_THRESHOLD_STR.upper() == "HIGH" else 0.5

	# Re-map env var name
	model_config = SettingsConfigDict(
		env_file=os.path.join(get_config_dir(), ".env"),
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
	COMPACTION_THRESHOLD: int = 10

	# -----------------------------------------------------------------------
	# WORKSPACE MEMORY COMPACTION
	# -----------------------------------------------------------------------
	WORKSPACE_MEMORY_COMPACT_BACKEND: str = "auto"
	WORKSPACE_MEMORY_COMPACT_MODEL: str = "flash"
	WORKSPACE_MEMORY_COMPACT_PROMPT: str = "seeds/memory/optimizer_prompt.txt"

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

	# Casual Override: keywords that signal the operator wants free-form conversation.
	# When detected in the prompt, Plugins 05+06 relax their directives regardless of color.
	# Comma-separated in .env: CASUAL_OVERRIDE_KEYWORDS="charlemos,relax,chill"
	CASUAL_OVERRIDE_KEYWORDS: List[str] = []

	@model_validator(mode="after")
	def _build_casual_keywords(self) -> "RedPillConfig":
		_default = "charlemos,charlar,charla,relax,relajado,hablemos,conversemos,off-topic,chill,quemar tokens,de guardia,no hay prisa"
		_env_raw = os.getenv("CASUAL_OVERRIDE_KEYWORDS", _default)
		self.CASUAL_OVERRIDE_KEYWORDS = [t.strip().lower() for t in _env_raw.split(",") if t.strip()]
		return self

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

	# LAZARUS SYNC & HEALER
	# -----------------------------------------------------------------------
	LAZARUS_SYNC_ENABLED: bool = True
	LAZARUS_SYNC_INTERVAL: int = 300
	LAZARUS_STATE_FILE: str = str(get_state_dir() / "lazarus_state.json")
	# Prevents autonomous git pushes from consuming machine resources or interrupting the operator's active IDE sessions during office hours (09:00 - 18:00).
	LAZARUS_OFFICE_HOURS_PROTECTION: bool = True

	# -----------------------------------------------------------------------
	# SEMANTIC RESONANCE & GRAPHRAG
	# -----------------------------------------------------------------------
	RESONANCE_ENABLED: bool = True
	RESONANCE_THRESHOLD: float = 0.4
	RESONANCE_INTERVAL: int = 600
	GRAPHIFY_RAG_ENABLED: bool = True
	CURIOSITY_ENGINE_ENABLED: bool = True
	CURIOSITY_PROFILE: str = "balanced"

	# -----------------------------------------------------------------------
	# INGESTION PLUGIN
	# -----------------------------------------------------------------------
	INGESTION_DIRECTORIES: List[str] = []

	@model_validator(mode="after")
	def _build_ingestion_directories(self) -> "RedPillConfig":
		from red_pill.core.paths import get_ingestion_dir

		_default = str(get_ingestion_dir())
		_env_raw = os.getenv("INGESTION_DIRECTORIES", _default)
		self.INGESTION_DIRECTORIES = [os.path.expanduser(p.strip()) for p in _env_raw.split(",") if p.strip()]
		return self

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
	MIN_TEXTURE_CHARS: int = 100  # Fragments below this length get no texture (hallucination guard, T3/T1)

	# ── Synaptic Axons (ADR-AXON-001) ──
	SLEEP_PLUGIN_AXONS: bool = True  # AxonWeaverPhase ON in shadow mode (weaves; read-path stays dark until the gate below)
	AXON_READ_ENABLED: bool = False  # Read-path: typed cascade injection + traversal reinforcement (enable after >=4 effective shadow runs)
	AXON_ALPHA: float = 0.7  # Weight of semantic similarity vs temporal proximity in W
	AXON_GATE: float = 0.5  # Composite threshold: connect when W = α·sim + (1-α)·(1-Δt/max) ≥ gate.
	# 0.6 rejected the true same-session pairs on real multilingual-384d data (cross-domain sims
	# run 0.28-0.35 → same-session W ≈ 0.50-0.53); 0.5 weaves those and still rejects noise (live
	# evidence 2026-07-18: correct pairs 0.525/0.509, junk ≤ 0.41).
	AXON_WINDOW_HOURS: float = 48.0  # Weaving work window per cycle (bounds nightly cost)
	AXON_DT_MAX_HOURS: float = 6.0  # Max temporal distance for a candidate pair
	AXON_BETA: float = 0.2  # Traversal reinforcement fraction (synthetic review = W·β)
	AXON_MAX_CROSS: int = 64  # Soft cap of cross-collection axons per engram (deferred pruning)

	# ── Chronicle ingestion hygiene ──
	CHRONICLE_STRIP_TOOL_PAYLOADS: bool = True  # Compact [TOOL: name target] markers instead of full JSON dumps (anti raw-noise)
	SLEEP_PLUGIN_HYGIENE: bool = True  # HygienePhase: purge empty engrams re-stitching the raw chain first

	# ── Texture space (T5: evocation by resonance) ──
	TEXTURE_SHADOW_ENABLED: bool = False  # Write texture_shadow points at consolidation (born dark)

	# ── Revision (Track R2: retroactive re-classification) ──
	SLEEP_PLUGIN_REVISION: bool = False  # RevisionPhase master switch (born dark)
	REVISION_BATCH_SIZE: int = 50  # Engrams re-classified per cycle (200 on beefy hardware)
	REVISION_DRY_RUN: bool = True  # Mark revision_would_move_to instead of moving (inspect first)
	SLEEP_SCROLL_LIMIT: int = 50  # Max engrams fetched per scroll batch (loop drains until empty)
	SLEEP_MAX_LLM_FAILURES: int = 5  # Thermal breaker: abort sleep after N consecutive LLM failures
	SLEEP_MIN_FREE_VRAM_MB: int = 1500  # Preflight: skip sleep if GPU has less free VRAM than this
	# When False (default), a read (search_and_reinforce) never DELETES eroded
	# engrams — it only hides them from the result. Forgetting belongs to the
	# sleep cycle (erode_work_hubs / rhizodb washout), not to a lookup.
	READ_PATH_PRUNING_ENABLED: bool = False

	# Sleep Cycle Plugin flags — each ritual individually activatable
	SLEEP_PLUGIN_USP: bool = True  # Operator Mood Profile refresh
	SLEEP_PLUGIN_DREAM: bool = True  # Oneiromancy (latent semantic association)
	SLEEP_PLUGIN_CONSOLIDATION: bool = True  # Memory consolidation (lazy sleep)
	SLEEP_PLUGIN_CHRONICLE: bool = True  # Ariadne's Thread + MCP archive search
	# └─ CHRONICLE=True (v6.5.0): antigravity decrypt→ingest pipeline operational.
	#   Gates archive_memories in MCP search_memory_research.
	#   Agent can auto-deactivate if archive_memories is empty.

	# -----------------------------------------------------------------------
	# PRE-HEATING (Oracle Protocol)
	# -----------------------------------------------------------------------
	PRE_HEATING_ENABLED: bool = True
	PRE_HEATING_INJECTION_MODE: str = "contextual"  # "contextual" | "raw"
	PRE_HEATING_SCORING_STRATEGY: str = "composite"  # "composite" | "intensity"
	PRE_HEATING_QUALITY_THRESHOLD: float = 5.0  # Minimum composite score to inject
	PRE_HEATING_MAX_FRAGMENTS: int = 3  # Max total (social + interaction)
	PRE_HEATING_MAX_CHARS_PER_FRAGMENT: int = 200  # For "raw" mode
	PRE_HEATING_LOOKBACK_HOURS: int = 48  # For interaction_memories
	PRE_HEATING_HOT_COLORS: Any = ["purple", "blue", "red"]
	PRE_HEATING_MAX_TRACKED_PROJECTS: int = 3  # Max tracked workspaces in PROJECT_STATUS

	# -----------------------------------------------------------------------
	# MOOD ORCHESTRATOR (Hito 5a-5b)
	# -----------------------------------------------------------------------
	MOOD_ORCHESTRATOR_ENABLED: bool = True  # Enable orchestrator for plugins 05-09

	# -----------------------------------------------------------------------
	# OPERATOR PROFILE UPDATE (Hito 4b)
	# -----------------------------------------------------------------------
	OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS: int = 24  # Hours between auto-updates

	@field_validator("PRE_HEATING_HOT_COLORS", mode="before")
	@classmethod
	def _parse_colors(cls, v: Any) -> Any:
		if isinstance(v, str):
			return [c.strip() for c in v.split(",") if c.strip()]
		return v

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
	SIGNAL_AMNESIA_HOURS: int = 8
	SIGNAL_MIGRAINE_VECTORS: int = 25000

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
	"social_memories": "rhizodb",
	"story_memories": "rhizodb",
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
_last_env_mtime: float = 0.0


def get_config() -> RedPillConfig:
	"""Return the singleton RedPillConfig instance, automatically reloading if .env has changed on disk."""
	global _last_env_mtime
	env_path = os.path.join(get_config_dir(), ".env")
	current_mtime = 0.0
	if os.path.exists(env_path):
		try:
			current_mtime = os.path.getmtime(env_path)
		except Exception:
			pass

	if current_mtime != _last_env_mtime:
		_last_env_mtime = current_mtime
		get_config_cached.cache_clear()

	cfg = get_config_cached(env_path)
	if _enterprise_overrides_store:
		cfg._enterprise_overrides.update(_enterprise_overrides_store)
	return cfg


@lru_cache(maxsize=1)
def get_config_cached(env_file: Optional[str] = None) -> RedPillConfig:
	if env_file:
		return RedPillConfig(_env_file=env_file)  # type: ignore[call-arg]
	return RedPillConfig()


def _clear_both_caches() -> None:
	global _last_env_mtime
	_last_env_mtime = 0.0
	get_config_cached.cache_clear()


get_config.cache_clear = _clear_both_caches  # type: ignore[attr-defined]


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
		get_config.cache_clear()  # type: ignore[attr-defined]


# Module-level aliases — backward compatibility (do NOT remove)
# All existing code does: import red_pill.config as cfg; cfg.QDRANT_HOST


def _cfg() -> RedPillConfig:
	"""Lazy accessor — deferred until first module-level alias is touched."""
	return get_config()


# Paths
# Dynamically handled via __getattr__
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
