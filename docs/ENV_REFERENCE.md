# Red Pill Protocol: Environment Configuration Reference (v7.0)

This document provides a comprehensive list of all parameters available in the `.env` file, their purposes, default values, and what specific behaviors they activate or deactivate within the Bünker ecosystem.

---

## 🏗️ Core Infrastructure Interfaces

### Database / Storage (Qdrant & Milvus)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `QDRANT_HOST` | `localhost` | The hostname or IP address of the Qdrant vector database. |
| `QDRANT_PORT` | `6333` | The port the Qdrant service is listening on. |
| `QDRANT_SCHEME` | `http` or `https`| The protocol used to communicate with Qdrant. Defaults to `https` for remote, `http` for local. |
| `QDRANT_API_KEY` | `None` | Authentication token for Qdrant. Required for secure shared environments or cloud clusters. |
| `MILVUS_ENABLED` | `False` | Activates connection to the HiveMind (Milvus). |
| `MILVUS_HOST` | `localhost` | Hostname for the Milvus server. |
| `MILVUS_PORT` | `19530` | Port for the Milvus server. |
| `MILVUS_SECURE`| `False` / `True` | Forces TLS encryption for Milvus connections (automatically True if remote). |
| `MILVUS_DB` | `default` | Goal database inside Milvus. |
| `MILVUS_NLIST` | `128` | Tuning parameter for the `IVF_FLAT` high-performance clustering index mapping. |
| `MILVUS_LITE_ENABLED` | `True` | Uses Milvus Lite (SQLite-based fallback) if a full Milvus cluster is unavailable. |

### Memory Processing (FastEmbed & Inference)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | The FastEmbed model. Multilingual (ES/EN), 384-dim. Changing it keeps the vector size (no schema wipe) but stored vectors are stale until recomputed with `scripts/reembed_collections.py --execute`. |
| `VECTOR_SIZE` | `384` | Expected dimensional output from the embedding model. Must match the model exactly. |
| `EXECUTION_PROVIDER`| `None` | Hardware acceleration strategy (e.g., `cpu`, `cuda`, `coreml`). |
| `FASTEMBED_CACHE_PATH` | `<project>/storage/models` | Absolute path to the locally cached embedding model weights. |
| `READ_PATH_PRUNING_ENABLED` | `False` | When `False`, `search_and_reinforce` hides eroded engrams from a result but never DELETES them — forgetting is the sleep cycle's job, not a lookup's. `True` restores the legacy destructive-read behavior. |
| `SLEEP_CHUNK_SIZE` | `6000` | Max characters per chunk the sleep cycle feeds the distiller. Large with a big-context distiller (qwen35_9b, 32k); keep `<=1000` with Samantha (4k ctx). |

---

## 🧬 Biological & Architectural Memory (FSRS & Decay)

### General Decay & Metabolism
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `METABOLISM_ENABLED` | `True` | Activates the core engine that forgets over time (entropic background decay). |
| `METABOLISM_STRATEGY`| `LAZY` | Calculation mode: `CLASSIC` run as a loop, `LAZY` calculated at query time. |
| `METABOLISM_COOLDOWN`| `3600` | Minimum seconds between global erosion cycles. |
| `ABSENCE_THRESHOLD`| `604800` (7 days)| Maximum idle time. If the operator doesn't connect for this duration, the Bünker triggers a global TTL refresh to prevent catastrophic mass-amnesia. |
| `MAX_SINK_TIME` | `2592000` (30 days)| Total max time an engram survives before a `Gran Purge` irrevocably destroys it. |
| `DECAY_STRATEGY` | `linear` | Mathematical model to apply score reduction (`linear` or `exponential`). |
| `EROSION_RATE` | `0.01` | How much reinforcement score is removed per cycle. At 0.01, standard memories last ~4 days without reinforcement. |
| `IMMUNITY_THRESHOLD`| `10.0` | Any memory achieving this reinforcement score becomes un-erasable ("immune"). |
| `REINFORCEMENT_INCREMENT`| `0.1` | Amount added to a memory's score every time it is actively recalled. |

### Emotional Seeding & Symbiosis
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `EMOTIONAL_SEED_FACTOR`| `3.0` | Score multiplier for emotional (non-neutral) memories. Gives intense memories higher starting scores (anxiety, joy) ensuring longer baseline survival. |
| `DEEP_RECALL_TRIGGERS`| `don't you remember,...` | Comma-separated list of queries that invoke high-intensity semantic search bypassing surface-level decay logic. |

### Graph Topology & Associations
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `PROPAGATION_FACTOR` | `0.5` | How much score transmits across the graph to associated nodes when a parent is recalled (e.g., 50% of the parent's `REINFORCEMENT_INCREMENT`). |
| `PROPAGATION_DEPTH`| `2` | Maximum recursive steps (hops) to traverse associations during recall (Hebb's Law). |
| `PROPAGATION_DECAY`| `0.5` | Exponential decay penalty per hop. Ensures ripple effects dampen into the graph. |
| `MAX_PROPAGATION_POINTS`| `20` | Maximum number of nodes that can receive reinforcement in a single query (Read Fan-Out). |
| `MAX_AXONS` | `500` | Maximum number of connections (edges) one node can form over its lifetime (Write Fan-In limit). |

### Synaptic Axons (ADR-AXON-001, v7.7.0)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `SLEEP_PLUGIN_AXONS` | `True` | AxonWeaverPhase master switch. Weaves cross-collection axons in shadow mode each sleep cycle. |
| `AXON_READ_ENABLED` | `False` | Typed cascade injection + traversal reinforcement at query time. Enable after ≥4 effective shadow runs and telemetry review. |
| `AXON_ALPHA` | `0.7` | Weight of semantic similarity vs temporal proximity in the axon weight `W`. |
| `AXON_GATE` | `0.5` | Connection threshold on `W`. Must stay below same-session `W` for real cross-domain similarities (~0.28-0.35 on multilingual-384d). |
| `AXON_WINDOW_HOURS` | `48` | Weaving work window per cycle (bounds nightly cost). |
| `AXON_DT_MAX_HOURS` | `6` | Maximum temporal distance for a candidate pair. |
| `AXON_BETA` | `0.2` | Traversal reinforcement fraction: a traversed axon applies `W·β` to its destination as a synthetic review. |
| `AXON_MAX_CROSS` | `64` | Soft cap of cross axons per engram (deferred pruning; hard ceiling at 2×). |

### Texture & Revision (v7.7.0)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `MIN_TEXTURE_CHARS` | `100` | Fragments below this length get no texture (hallucination guard). |
| `TEXTURE_SHADOW_ENABLED` | `False` | Write searchable `texture_shadow` points at consolidation (T5 resonance search). |
| `SLEEP_PLUGIN_REVISION` | `False` | RevisionPhase master switch (retroactive re-classification). |
| `REVISION_BATCH_SIZE` | `50` | Engrams re-classified per sleep cycle (200 on beefy hardware). |
| `REVISION_DRY_RUN` | `True` | Mark `revision_would_move_to` instead of moving engrams. |
| `CHRONICLE_STRIP_TOOL_PAYLOADS` | `True` | Chronicle ingestion writes compact `[TOOL: name target]` / head-only result markers instead of full JSON dumps (anti raw-noise). |
| `SLEEP_PLUGIN_HYGIENE` | `True` | HygienePhase: purge empty engrams each cycle, re-stitching the raw_parent chain first (immune empties are reported, never touched). |

### Memory Engrams (Fragmenter)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `CHUNK_THRESHOLD` | `800` | If a text memory exceeds this character limit, it splits into fragments. |
| `CHUNK_SIZE` | `500` | Target size for engram chunks after splitting. |
| `CHUNK_OVERLAP` | `100` | Number of overlapping characters to preserve semantic transition between chunks. |

### Bayesian Core (Logic & Work Memories)
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `BAYESIAN_COLLECTIONS` | `skill,work,directive` | Comma-separated list of collections that use technical Bayesian inference instead of affect-based FSRS logic. |
| `BAYESIAN_STABILITY_KAPPA`| `0.05` | Rate of uncertainty accumulation (`beta`) per day. Higher means faster forgetting of technical utility. |
| `BAYESIAN_REINFORCEMENT_GAIN`| `1.0` | Amount of certainty (`alpha`) added when an operator actively uses this technical knowledge. |

---

## 🤖 Dynamic Protocol (MCP & Interceptor)

### Agent & Operator Definition
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `AGENT_NAME` | `Agente` | Fallback name used by the agent during interactions. |
| `USER_NAME` | `Operador` | Overrides the Operator name in the Bünker to ensure privacy beyond system logic. |

### MCP Kernel & Interceptor
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `INTERCEPTOR_ENABLED`| `False` | Toggles the Bünker's active middleware injection via MCP. If `True`, intercepts IDE prompts to dynamically load context from Qdrant. |
| `COMPACTION_THRESHOLD`| `10` | The number of consecutive context compactions to wait before executing a full session context refresh (prevents feedback loops). |
| `SEMANTIC_INTENT_THRESHOLD`| `Low` (0.5) | `High` (0.75) or `Low` (0.5). Sets how literal the matching needs to be for context injection. |
| `PULSE_ENABLED` | `True` | Activates autonomous background synthesis and maintenance operations. |
| `PULSE_INTERVAL` | `3600` | Interval in seconds between Sovereign Pulses. |
| `LAZARUS_SYNC_ENABLED` | `True` | Activates constant state-sync to prevent process interruptions from losing RAM context. |
| `LAZARUS_SYNC_INTERVAL` | `300` | Interval in seconds (5 min) for the Lazarus checkpoint generator. |
| `RESONANCE_ENABLED`| `True` | Enables automated "Aha!" moments by checking similarities across previously idle engrams. |
| `RESONANCE_THRESHOLD`| `0.4` | How close two disparate memories need to be in vector space to trigger forced integration. |


### 🏎️ Emotional Ferrari Protocol (v6.3.0)

Plugins 05–10. Each is independently toggleable.

| Parameter | Default | Plugin | Description |
| :--- | :--- | :--- | :--- |
| `MOOD_ORCHESTRATOR_ENABLED` | `True` | 05 | Enable orchestrator that consolidates plugins 05-09 in a single pass |
| `COGNITIVE_ROUTER_ENABLED` | `True` | 05 | `COGNITIVE_COLOR`: 3-day USP baseline (slow signal; meaning lives in the CHROMA KEY legend). |
| `TONE_ADAPTER_ENABLED` | `True` | 06 | `TONE_COLOR`: 4h session window (fast signal, Overnight Therapy reset; meaning in the CHROMA KEY legend). |
| `WORK_MODE_KEYWORDS` | ES+EN seed (`arregla,fix,implementa,…`) | 05 | Comma-separated vocabulary that locks the engine-brake latch into work mode. Operator-customizable per language and trade — nothing hardcoded in code (v7.16.0). |
| `CASUAL_OVERRIDE_KEYWORDS` | ES seed (`charlemos,relax,chill,…`) | 05/06 | Comma-separated vocabulary that flips the latch into casual mode instantly. Operator-customizable. |
| `MOOD_ANALYTICS_ENABLED` | `True` | 07 | Trend analysis over last 15 memories (stable/improving/deteriorating). |
| `EMOTIVE_RECALL_ENABLED` | `True` | 08 | Semantic echo of past same-color interactions. |
| `PROACTIVE_SIGNAL_ENABLED` | `True` | 09 | Alert + pain signal on sustained RED > threshold consecutive memories. |
| `PROACTIVE_SIGNAL_RED_THRESHOLD` | `5` | 09 | Consecutive RED memories before care signal is emitted. |
| `PREDICTIVE_PRELOAD_ENABLED` | `True` | 10 | Preloads work/social context by color: cyan/emerald/purple→work, blue/red→social. |

### 💤 Sleep Cycle Plugins (v6.3.0)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `SLEEP_PLUGIN_USP` | `True` | Refresh Operator Mood Profile (USP) during sleep cycle. |
| `SLEEP_PLUGIN_DREAM` | `True` | Oneiromancy: latent semantic association. |
| `SLEEP_PLUGIN_CONSOLIDATION` | `True` | Hub Synthesis + memory consolidation. |
| `SLEEP_PLUGIN_CHRONICLE` | `True` | Ariadne's Thread weaving across all 4 collections. Requires `ANTIGRAVITY_KEY`. |
| `SLEEP_MIN_FREE_VRAM_MB` | `1500` | Minimum free VRAM (MB) required to start the sleep cycle. If the GPU has less free VRAM at 03:00 (e.g. occupied by a game or other model), the cycle aborts gracefully and emits a muted `vram_busy` pain signal. Set to `0` to disable the preflight check. CPU-only systems are unaffected. |
| `SLEEP_CUTOFF_ENABLED` | `True` | Bounds the consolidation drain to engrams with `timestamp <=` the instant the cycle started (persisted in the job checkpoint). Engrams written while the cycle runs stay buffered for the next cycle, so the drain terminates deterministically. |

### 🔧 Operator Profile & Pre-Heating

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS` | `24` | Hours between automatic `operator_profile.md` updates during sleep ritual. |
| `RECENT_ACTIVITY_UPDATE_INTERVAL_HOURS` | `4` | Freshness window for `recent_activity.md`: RecentActivityPhase skips re-synthesis while the artifact is younger than this. |
| `PRE_HEATING_MAX_TRACKED_PROJECTS` | `3` | Max tracked workspaces to show in PROJECT_STATUS (opt-in via `track: true` in workspaces.yaml). |

### ⚖️ BE_WATER Adaptive Payload (v6.3.0)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `MAX_PAYLOAD_CHARS` | `auto` | Auto-computed from VRAM: <4 GB→1 000, 4–8 GB→5 000, >8 GB→unlimited. Override in `.env`. |

---

## 🔌 IDE Bridge & Extractor Cascades (v7.3.1)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `IDE_BACKEND` | `auto` | Execution backend selector (`auto`, `agy`, `grpc`, `claude`, `opencode`, or `local`). `auto` prefers `agy` if available. |
| `OPENCODE_SERVER_URL` | | URL of persistent `opencode serve` instance (e.g. `http://localhost:4096`). Enables attached mode, avoiding MCP cold-start. |
| `OPENCODE_BIN` | | Explicit path to the `opencode` binary. Wins over PATH resolution — the robust option for service-manager contexts. |
| `OPENCODE_SCRIBE_PLUGIN` | `False` | Set to `true` when the `redpill-scribe` OpenCode plugin handles persistence. Disables bridge `_scribe_relay()` to avoid double-writes. |
| `AUTONOMOUS_AGY_ENABLED` | `False` | Gathers and gates autonomous Flash-consuming operations like cognitive queue or entropy executor. |
| `TELEGRAM_BRIDGE_CASCADE` | `[]` | JSON-encoded fallback cascade of model targets for Telegram/inbox processing. Per-target fields: `backend`, `model`, `effort`, `timeout` (optional, overrides the method timeout for that target). Example: `'[{"backend":"opencode","model":"opencode-go/deepseek-v4-pro","timeout":300},{"backend":"opencode","model":"opencode/deepseek-v4-flash-free"}]'`. |
| `TELEGRAM_INLINE_TIMEOUT` | `120` | Fast-path inline timeout (s) for Telegram conversational messages (D3). Passed as the method timeout to `CascadeBridge.prompt()`; a per-target `timeout` in `TELEGRAM_BRIDGE_CASCADE` overrides it for that target (D14). |
| `AWAKENING_BRIDGE_CASCADE` | `[]` | JSON-encoded fallback cascade of model targets for autonomous awakening runs. |
| `DEFAULT_MINION_BRIDGE_CASCADE` | `[]` | JSON-encoded fallback cascade of model targets for background agéntic minions if no model is explicitly requested. |
| `CHRONICLE_PLUGINS` | `["antigravity", "claude_code"]` | List of enabled sequential extraction plugins to pull transcripts during sleep cycle. |

> **Catálogo curado de modelos (RFC_TELEGRAM_RESILIENCE §2A/D6/D20)**: el archivo
> `$XDG_CONFIG_HOME/red-pill/model_catalog.yaml` (auto-seeded desde
> `examples/model_catalog.yaml.example`) es la fuente de verdad de modelos.
> `red-pill telegram models` lista el catálogo; `red-pill telegram roles` los
> roles. Los comandos Telegram `/models`, `/model`, `/defaults`, `/deferred`,
> `/queue`, `/mission` operan sobre él. Si el catálogo no existe, el runtime cae a
> la cascade de `.env` (compatibilidad).

> **⚠️ opencode + service managers (PATH requirement)**
>
> When `opencode` is used (as `IDE_BACKEND` or in any `*_BRIDGE_CASCADE`), the `opencode` binary must be resolvable from the **service manager's** environment — not just your login shell. Service managers run with a minimal PATH:
>
> - **Linux (systemd user units)**: add the install dir (e.g. `~/.opencode/bin`) to `Environment="PATH=..."` in `~/.config/systemd/user/redpill-*.service`, then `systemctl --user daemon-reload`.
> - **macOS (launchd)**: set `PATH` under `EnvironmentVariables` in the plist.
> - **Windows (Task Scheduler)**: put the install dir on the user/machine PATH, or set `OPENCODE_BIN`.
>
> Resolution order: `OPENCODE_BIN` env → `$PATH` → `~/.opencode/bin` (probed as last resort). If the binary is missing, bridge construction now fails **loudly** in the logs and the worker never falls back to the legacy Antigravity IDE path for non-IDE cascades — before v7.15.x this degraded silently and pulses crashed against a dead IDE.

---

## 📼 Memento Chronicle (RFC-002)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `MEMENTO_ROOT` | `""` (→ `~/.local/share/red-pill/memento/`) | Root of the on-disk chronicle tree. Operator-overridable. |
| `MEMENTO_SOURCES` | `[]` (→ follows `CHRONICLE_ARCHIVE_SOURCES`) | Per-source enable/disable for the Memento render. |
| `MEMENTO_RAW_ENABLED` | `True` | Write `raw/` provider-native backups + `meta.json` (the single backup point; unscrubbed — never in git). |
| `MEMENTO_SPLIT_MAX_MESSAGES` | `200` | Split trigger + per-chunk cap (backstop; chars bind first). |
| `MEMENTO_SPLIT_MAX_CHARS` | `12000` | Split trigger + per-chunk budget. **Hardware-derived — recalculate per deployment (see below).** |
| `MEMENTO_EXTRA_SOURCES` | `["memory_queue"]` | Memento-only sources: capture to the tree without touching the Qdrant archive. `memory_queue` = MCP-only turns (MUST 10). `antigravity_export` = frozen early-era snapshot (47 MD, `conversations_export`, operator legacy) — **opt-in**: `MEMENTO_EXTRA_SOURCES=memory_queue,antigravity_export` — absent by default because the path is a local snapshot, not a live store, and clean installs don't have it. |
| `INTERACTION_MEMORIES_TTL_HOURS` | `72` | Janitor TTL backstop over the interaction buffer. Must exceed `PRE_HEATING_LOOKBACK_HOURS` (the plugin refuses otherwise). |
| `MEMENTO_QUEUE_RETENTION_DAYS` | `7` | Safety margin before purging completed memory_queue rows whose group is already rendered. |
| `MEMENTO_REFINE_MIN_SIGNIFICANCE` | `0.3` | Below this, refine writes no file for the section (permissive selection). |
| `MEMENTO_GATE_MIN_SIGNIFICANCE` | `0.5` | **Provisional (Q4 open)**: threshold of the shadow would-ingest decision. |
| `MEMENTO_AGENTIC_NIGHT_LIMIT` | `20` | Sessions distilled+refined per nightly chronicle run (bounds local-LLM cost). |
| `MEMENTO_GATE_ENFORCED` | `False` | **Phase 4 switch.** Flip ONLY with operator approval backed by shadow evidence: chronicle stops ingesting below-threshold sessions into archive_memories. |

> ⚠️ **`MEMENTO_SPLIT_MAX_CHARS` is NOT universal.** Splits are the work units
> the local distill LLM consumes (RFC-002 §4.2), so the budget must be derived
> from the smallest context the local model runs with on *this* hardware:
> `MEMENTO_SPLIT_MAX_CHARS ≈ (n_ctx − ~800 prompt − ~600 output) × 3 chars/token`.
> The `12000` default assumes the 4GB-VRAM floor (`n_ctx=6144`,
> `scripts/llama_cli_runner.py`; EdgeEngine runs 8192). Whoever configures a
> deployment — operator or agent — must recompute it when the hardware or the
> model context changes, and re-run `memento_migrate --all` to re-chunk.

---

## ☁️ Persistence & Encryption (Cloud Vault)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `CLOUD_VAULT_ENABLED` | `False` | Toggles AES-256 encrypted auto-exports to cloud services. |
| `CLOUD_VAULT_PROVIDER`| `google_drive` | Only `google_drive` supported. |
| `CLOUD_VAULT_FOLDER_ID`| `""` | The absolute folder ID in the Drive account to stage exports. |
| `CLOUD_SERVICE_ACCOUNT_FILE`| `*/service_account.json`| Auto-generated path to G-Cloud credentials. |
| `CLOUD_VAULT_QUOTA_MB` | `500` | Maximum size in MB stored on the cloud. |
| `CLOUD_VAULT_RESERVE_COUNT`| `4` | How many recent full Soul Kits to keep before pruning older ones. |
| `CLOUD_VAULT_GPG_PASSPHRASE`| `N/A` | Critical: Sets the symmetric AES-256 payload password. Used dynamically but not printed in `.env.example`. |

---

## 🎭 Affective Calibration (ACE & Chroma)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `AFFECT_MODEL` | `PIONEER` | Affective dictionary behavior. Options: `PIONEER` (Native RP rules), `ACADEMIC` (Warriner 2013 lexicons), `CUSTOM` (Your parameters). |
| `AFFECT_CUSTOM_OVERRIDES`| `{}` | A JSON Dictionary mapping emotions to custom Valence/Arousal weights. Only triggers if `AFFECT_MODEL=CUSTOM`. |
| `DYNAMIC_EMOTION_SYNC`| `True` | Let the agent auto-derive its Skin based on the dominant emotional context of recent interactions. |
| `MULTI_EMOTION_INFERENCE`| `True` | Enables deriving a primary and secondary emotion for high-complexity engrams. |

---

## 🛠️ Diagnostics
| Parameter | Default | Description |
| :--- | :--- | :--- |
| `LOG_LEVEL` | `INFO` | Standard application logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LOG_JSON` | `False` | Experimental. Replaces string logs with parseable JSON structures for ELK/Datadog ingrowth. |
| `NOTIFICATIONS_ENABLED`| `True` | Send `osd-notify` DBUS messages to the desktop when background tasks complete. |
| `NOTIFICATION_SOUND` | `False` | Experimental: Play a 770Hz pulse on key Bünker actions. |

---

## 🛰️ Swarm Messaging (MLS B1 / pure-mls)

> Since v6.1.3, all Swarm messages are encrypted end-to-end using **RFC 9420 TreeKEM** via the `pure_mls` library. Legacy DH and SovereignGroup modes have been removed.

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `SWARM_SHARED_SECRET` | `""` | **Required.** The community admission password. Used as the HMAC-SHA256 key to sign/verify every `KeyPackage` published to Firebase. Agents without this secret cannot fake a valid `admission_token` and will be silently dropped on `resolve_alias()`. Must be identical between all community members (distributed out-of-band by the operator). |
| `SWARM_TELEMETRY_LEVEL`| `MINIMUM` | Controls Swarm-level logging verbosity. Options: `NONE`, `MINIMUM`, `FULL`. |

### How MLS B1 Works (Quick Reference)

```
1. swarm_subscribe  →  publishes KeyPackage + HMAC(SWARM_SHARED_SECRET, kp_bytes) to Firebase
2. swarm_send_message  →  resolve_alias verifies token → add_member → push_welcome → encrypt → send
3. swarm_check_mailbox  →  pop_welcome → process_welcome (join group) → decrypt inbox
```

> [!IMPORTANT]
> `SWARM_SHARED_SECRET` must be **32+ characters** and shared **out-of-band** (Signal/in-person) between all Swarm operators before the first subscription. After the initial group formation, TreeKEM handles all key rotation automatically — you never need to re-share the secret.
