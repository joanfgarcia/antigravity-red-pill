# Red Pill Protocol: Environment Configuration Reference (v6.1)

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
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | The FastEmbed model to use. Modifying this requires completely wiping the vector database. |
| `VECTOR_SIZE` | `384` | Expected dimensional output from the embedding model. Must match the model exactly. |
| `EXECUTION_PROVIDER`| `None` | Hardware acceleration strategy (e.g., `cpu`, `cuda`, `coreml`). |
| `FASTEMBED_CACHE_PATH` | `<project>/storage/models` | Absolute path to the locally cached embedding model weights. |

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
| `COGNITIVE_ROUTER_ENABLED` | `True` | 05 | Routes *task type* by color (architecture, maintenance, empathy). |
| `TONE_ADAPTER_ENABLED` | `True` | 06 | Adapts *verbal style* (precise/warm/ultra-concise). |
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

### ⚖️ BE_WATER Adaptive Payload (v6.3.0)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `MAX_PAYLOAD_CHARS` | `auto` | Auto-computed from VRAM: <4 GB→1 000, 4–8 GB→5 000, >8 GB→unlimited. Override in `.env`. |

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
