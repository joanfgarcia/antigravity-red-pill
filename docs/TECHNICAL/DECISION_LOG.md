# Red Pill Protocol: Decision Log

This document records the architectural and philosophical pivots of the project.

---

## [AD-025] Job DAG — el dag_job como plantilla genérica recursiva de composición
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: forge_job y sleep_job duplicaban la MISMA mecánica (checkpoint, on_fail por unidad, telemetría, control transferible). Dos drivers que solo cambiaban en el contenido de sus unidades. El DAG generaliza esa mecánica en un solo driver y reduce forge/sleep a recetas (configuración de etapas).
**Decision**:
- `dag_job` es la plantilla genérica: un árbol RECURSIVO de etapas. Cada etapa es **atómica** (un minion del MinionFactory: agéntico o no) **o compuesta** (sub_etapas con topología local). La recursión unifica todo: panel = sub-etapa paralela, sleep = receta secuencial, forge = receta mixta.
- `forge_job`/`sleep_job` dejan de registrarse como drivers. Sus manifests pasan a ser recetas del dag_job. Los archivos quedan importables (legacy) para jobs previos y tests; limpieza física diferida.
- Etapa agéntica se distingue por RESOLUCIÓN del minion (isinstance AgentMinion), no por un campo `type` redundante. `type` existe como red de VALIDACIÓN cruzada (type↔minion), no como fuente de comportamiento.
- `parallel: true` es **INTENCIÓN declarativa, no obligación**: el orquestador decide cuándo paraleliza (max_parallel_level, default 2). Nivel mayor → secuencial sin error.
- Checkpoint por sub-etapa con flags del padre: cada etapa atómica persiste SU reporte en `.cell/reports/<ruta>.json`; el padre solo marca `stage_flags`. Determinismo por identidad de ruta (ids aplanados), no por orden de hilos.
**Por qué esto y no alternativas**: no un driver por caso (era la duplicación que motivó el RFC); no tipo de etapa propio (el kernel ya tenía la unidad — MinionFactory); no réplica de checkpoints en el padre (se elimina el problema del orden de hilos del fan-out, ver AD-026).

---

## [AD-026] DAG dinámico ACOTADO — branching y fan-out sí, reescritura agéntica no
**Date**: 2026-08-08
**Status**: ACCEPTED (diseño) — implementación futura (no entró en el PR #84 / v7.17.0).
**Context**: la pregunta "¿DAG dinámico?" se descompuso en tres capacidades distintas al repensar el RFC tras implementarlo. AutoGPT/BabyAGI fracasaron en "autonomía total con plan emergente" por goal drift (el agente justifica lo hecho en vez de avanzar). La lección: la autonomía sin anclas deriva.
**Decision**:
1. **Branching condicional — SÍ (futuro)**: etapa gate (minion agéntico) que devuelve un veredicto ∈ categorías DECLARADAS en el manifest → el DAG elige la rama. El árbol completo se declara al inicio; el validador no inventa ramas, solo elige entre las declaradas.
2. **Fan-out por items — SÍ (futuro)**: una etapa devuelve una lista; el DAG instancia N veces una etapa plantilla. La lista viaja al checkpoint (determinista).
3. **Reescritura arbitraria del manifest por un agente — NO**: pierde determinismo, auditoría y resume limpio. El operador/main-loop ya "reescribe" vía control transferible (job_transfer → inline → job_checkpoint → job_resume).
**Regla de oro**: el agente NO reescribe el plan — declara un resultado, el DAG interpreta dentro de los límites del manifest.
**Referencia de patrones**: LangGraph (conditional edges), Airflow (BranchPythonOperator / Dynamic Task Mapping), Temporal (signals): todos grafo estático + decisión en el nodo.

---

## [AD-027] Serialización del minion — la hace el DAG, no el minion (opción 3)
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: los minions del MinionFactory devuelven dict en memoria (`{status, response, error, ...}`). La alternativa natural era que el minion escribiera `.cell/reports/<id>.json` él mismo, acoplando todos los minions al contrato de reporte del DAG.
**Decision**: el `dag_job` serializa: tras `minion.execute()`, el DAG escribe el dict a `.cell/reports/<ruta>.json`. *(Enmienda 2026-08-14: en etapas `type: agent` el envelope va a `<ruta>.envelope.json` — ahí el reporte de verdad lo escribe el agente conforme al schema de su rol y el DAG lo pisaba, dejando al gate zero-trust validando envelopes.)* Los minions existentes NO se tocan (ni parámetro en el constructor, ni herencia JobMinion). Un minion que genere un artefacto grande puede escribir su propio archivo y devolver solo el resumen — sin mecanismo especial.
**Por qué**: los minions son unidades puras (devuelven dict); la serialización es un contrato del consumidor (el DAG), no del minion. El carril cognitivo usa los mismos minions sin serialización.

---

## [AD-028] Fail-safe de modelos en TODAS las etapas agénticas del árbol
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0; extiende PR #83).
**Context**: el PR #83 bloqueaba agentic_job/forge_job sin modelo real (flash = placeholder). El dag_job introduce N etapas agénticas por misión; validar solo el job no basta.
**Decision**: `validate()` del dag_job recorre el árbol recursivamente: TODA etapa `type: agent` exige `model` real (no `flash`) + `prompt`, validado EN EL SUBMIT — antes de lanzar CUALQUIER etapa. El MCP/CLI bloquean igual.
**Por qué**: una misión con una etapa agéntica sin configurar fallaría 3 intentos después y a las 3 de la mañana. El fail-safe lo detecta al encolar.

---

## [AD-029] Exención nocturna del runner generalizada (nightly_exempt)
**Date**: 2026-08-08
**Status**: ACCEPTED — mergeado con el PR #84 (v7.17.0).
**Context**: el runner difiere todos los driver jobs mientras el ciclo nocturno está activo (prioridad de la noche). La exención anti-deadlock era por source exacto (`sleep_job`): el sueño no podía auto-diferirse entre unidades. Al migrar sleep a receta dag_job, esa exención se rompía (el dag_job de sueño se diferiría a sí mismo → inanición).
**Decision**: la exención pasa a un flag declarativo en el payload: `nightly_exempt: true` (lo declara la receta sleep). El runner exime ese flag además del source legacy. No es un chequeo por nombre de driver.

---

## [AD-024] Murky Memory Policy (Self-Evocation Enforcement)
**Date**: 2026-07-19
**Status**: PROPOSED — decision deliberately deferred by the Operator ("hay que pensarlo bien").
**Context**: the Self-Evocation Principle (a memory must let you intuit what it pointed to when the artifact is gone — the Operator's "book test") is enforced at ingestion (compact self-evocative tool markers) and audited by the HygienePhase, which counts **murky pointers** (engrams that are ONLY an opaque reference: path/url/uuid with <4 words of semantic residue) every cycle, report-only. First live audit: 15 in `work_memories`, 0 in `social_memories`.
**Options on the table** (Operator's sketch, 2026-07-19):
1. Purge them.
2. Attempt enrichment (feasibility unproven — the referent may be recoverable from siblings/context or already gone).
3. A `turbio` flag acting as an **erosion accelerator** and stripping the `immune` label — murky memories fade faster instead of dying instantly.
**Constraint**: whatever is decided ships as a versioned `update_ritual.py` step per the engram-migration mandate. Until then: report-only, never touch.

---

## [AD-023] Recall Remediation — Bayesian Calibration, Non-Hiding Reads & Orphan-Chunk Promotion
**Date**: 2026-07-18
**Context**: v7.7.0 — live diagnosis during the axon tests: `search_and_reinforce` on `work_memories` (16,512 points) returned 0 hits for almost any query under `METABOLISM_STRATEGY=LAZY`, even with `deep_recall=True`. The 7.7.0 axons and texture layers are useless if direct recall returns empty.
**Status**: EXECUTED — code fix + **live engram mass-update applied 2026-07-18** (see §4; any agent reasoning about engram payloads must read this section).

### 1. Root causes (four, measured — not assumed)
1. **Born-dead threshold**: `BayesianEngine.deletion_threshold` was 0.5 — exactly the uniform-prior mean E[Beta(1,1)]. Every engram without reinforcement history (α ≤ β: **99.0%** of the collection) got `_delete=True` at t=0. Not a timestamp problem: median `last_recalled_at` age was 1 day (Absence Guard keeps them fresh).
2. **Death-spiral reads**: the read path *hid* eroded hits, so they could never be reinforced — yet a single recall (+0.5 α) is enough to rescue a prior engram. Hiding starved the rehab loop by design. `immune` engrams (53.7% — the `raw_parent` verbatims) were hidden too, despite every sleep path honoring the flag.
3. **Dead erosion filter**: `erode_work_hubs` scrolled `metadata.lazarus_phase` (nested) but the field is stored top-level — matched **0 of 1,242 hubs**. Sleep-side hub erosion never ran (which accidentally preserved the data).
4. **Hub-less turns invisible**: a hub is only synthesized when >1 chunk survives distillation, so single-survivor turns lived only as `sequence_chunk` — structurally excluded from search. Measured: 1,553/2,359 work parents and 227/253 social parents had **no searchable representative** (~2/3 of consolidated turns).

### 2. Decision
- Threshold 0.5 → **0.2** (a prior engram now survives ~19 recall-free days: `1/(2+ln(1+t)) = 0.2 → t = e³−1`). Invariant: the Bayesian deletion threshold must sit **strictly below the prior mean 0.5**.
- Reads never hide: eroded hits return flagged `_eroded=True`, demoted below healthy hits, and are reinforced (organic rehabilitation). Forgetting belongs to the sleep cycle. `READ_PATH_PRUNING_ENABLED=True` keeps the legacy destructive read as explicit opt-in. `immune` is honored on the read path and axon traversal.
- `erode_work_hubs`: filter fixed to top-level `lazarus_phase`; its hardcoded 0.3 threshold replaced by `get_memory_engine("bayesian").deletion_threshold` (single source of truth).
- **Option A (operator-ratified)**: a single-survivor turn's lone chunk IS its hub. Consolidation promotes it inline (`_promote_lone_chunk_to_hub`: phase flip + thread weaving + texture shadow). `promote_orphan_chunks` runs every sleep cycle as `OrphanPromotionPhase` (after Consolidation, before AxonWeaver) — self-healing for any future hub-synthesis failure. Option B (a new searchable phase) was rejected as a patch, not a fix.

### 3. Rejected alternative
Mass synthetic rehabilitation review (Eje 3 of the memoria_bunker retrospective) was **not needed**: the data was never corrupted, only misjudged. Recalibration + recall-driven reinforcement rehabilitates organically.

### 4. ⚠️ Engram mass-update (live migration, 2026-07-18)
`promote_orphan_chunks(mm)` was executed against the live Bünker. Agents that update themselves or reason about payload schemas must account for:
- **1,553** work + **227** social hub-less parents had their **newest chunk flipped** `sequence_chunk` → `synthesis_hub` (`node_type` set accordingly). Work hubs went 1,242 → 2,795.
- Promoted engrams carry **`promoted_from: "sequence_chunk"`** (provenance marker — they are single-chunk distillates, not LLM syntheses).
- Multi-chunk parents (**597** work + **63** social) additionally carry **`hub_rebuild_pending: true`**: a queue marker for a future LLM re-synthesis pass. Until that pass exists, treat these as partial representatives (newest chunk only). Do NOT strip the flag without synthesizing a real hub.
- The migration is **idempotent** (re-run reports 0 pending) and did not touch: parents that already had a hub, `raw_parent` verbatims, or chunk siblings (still `sequence_chunk`, still search-excluded).
- New read-path contract: results may include `_eroded: true` (decayed below threshold, kept for rehab — rank accordingly) — this is an ephemeral response field, never persisted.
- Since erosion now actually runs, promoted hubs enter the normal hub lifecycle (β+0.5 per unrecalled cycle, forgotten at utility ≤ 0.2 — ~6 cycles from prior).

### 5. Verification
Live E2E: 0 hits → 6–8 hits/query on `work_memories`; promoted chunks surface in real queries (e.g. 4/7 hits for "umbral bayesiano decaimiento"). Full suite: 1,064 passed. Tests: `test_lazy_decay_calibration.py`, `test_read_path_pruning.py` (rewritten contract), `test_erode_work_hubs.py`, `test_orphan_chunk_promotion.py`.

---

## [ADR-SLEEP-001] Sleep Engine Decomposition — Agnostic Phase Pipeline
**Date**: 2026-05-31 (deferred) → 2026-07-16 (DONE)
**Context**: `sleep.py` was a God Class (~1300 LOC). The original ADR (in the module docstring) deferred decomposition with an explicit trigger: revisit at >1200 LOC **or** when new phases are needed.
**Status**: DONE — both triggers fired (the file crossed 1200 LOC and gained per-phase VRAM gating).

### Decision
Two phases, verified commit-by-commit against the existing `test_sleep*` suite:
- **Phase A (zero behavior change)**: extract the library layer to focused modules — `chunker`, `categorizer`, `distiller`, `ephemeral_server`, `thread_weaver`, `maintenance`. `sleep.py` 1325 → 545 LOC, re-exporting for back-compat.
- **Phase B (new capability)**: `perform_sleep_cycle` becomes a thin, agnostic runner over an ordered `SleepPhase` pipeline (`metabolism/phases/`, mirroring the JanitorPlugin/SentinelPlugin pattern). The tightly-coupled drain loop stays intact inside `ConsolidationPhase` (`requires_gpu`), as the original ADR warned it must; erosion, washout and evolution are CPU-only phases.

### Why it earned its keep (not just tidiness)
Each phase declares `requires_gpu`, so the runner defers **only** the GPU-heavy consolidation when the card is committed to training — a benign, non-escalating `vram_busy` *status* signal, self-clearing on the next successful cycle — while CPU-only maintenance still runs. **Partial deferral** replaces the old all-or-nothing VRAM abort. `sleep.py` ended at ~100 LOC; full suite green (961 passed).

---

## [AD-022] Distiller Model Selection — Granite-4.1-8B (primary) + Hermes-3-8B (fallback)
**Date**: 2026-07-13  
**Context**: v7.5.0 — choosing the sleep-cycle distiller after the AD-021 remediation  
**Status**: ACCEPTED (operator-ratified); live-config activation pending  

### 1. The Problem
The distiller is the most quality-critical model in the Bünker (it decides what becomes a
permanent engram and how it is labelled). Samantha (Mistral-7B, 2023) was retired. The question
was which small local model replaces it. Candidates were benchmarked, not chosen by reputation.

### 2. The Evidence (measured, not assumed)
Two GPU bake-offs (`scripts/distiller_bakeoff.py`, `scripts/distiller_fidelity.py`, RTX 5070 8 GB,
2026-07-13). Full raw outputs: [DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md) /
[DISTILLER_FIDELITY.md](../BENCHMARKS/DISTILLER_FIDELITY.md).

**Format aptitude** (technical / philosophical / noise / emotional probes):

| Model | JSON | Spanish | No `<think>` | Emotion ok | Avg latency |
| :--- | :--- | :--- | :--- | :--- | :--- |
| granite_8b | 4/4 | 4/4 | 4/4 | 4/4 | 1.0 s |
| hermes_8b | 4/4 | 4/4 | 4/4 | 4/4 | 1.1 s |
| piaget_8b | 4/4 | 4/4 | 0/4 | 4/4 | 0.9 s |
| beck_8b | 4/4 | 4/4 | 0/4 | 4/4 | 1.0 s |
| qwen35_9b | 1/4 | 1/4 | 4/4 | 1/4 | 9.4 s |
| samantha | 0/4 | 0/4 | 4/4 | 0/4 | 2.6 s |

**Fidelity** (does the summary capture BOTH the user and the assistant), BASE vs TUNED prompt:

| Model | BASE both-sides | TUNED both-sides |
| :--- | :--- | :--- |
| hermes_8b | 2/3 | 3/3 |
| granite_8b | 2/3 | 3/3 |

Net: `granite_8b` and `hermes_8b` co-win on every measured axis. The fidelity gap was a *prompt*
problem (fixed for all models in the production `distill_engram` prompt), not a model deficiency.

### 3. The Decision
**Granite-4.1-8B is the primary distiller; Hermes-3-8B is retained as fallback** (keeps
`logic`/`emotional_intelligence` capabilities). Granite carries the sole `distillation` capability;
`MINION_PROFILE=granite_8b`.

### 4. Rationale (tiebreakers, since the models tied on merit)
1. **License**: Granite is **Apache-2.0**; Hermes inherits the Llama-3.1 Community License
   (field-of-use + 700M-MAU clauses). For a sovereign, redistributable project the piece that
   distills memory should be the most permissively licensed — decisive, and non-speculative.
2. **Philosophy fit**: Granite is IBM's deliberately-small, structured-output/RAG/tool-use
   workhorse — a "small expert" by design, matching red-pill's model philosophy.
3. **Trajectory**: newer, actively maintained, hybrid-arch efficiency, plausibly fresher/cleaner
   training data (unverified — the bake-off, not recency, is the evidence).
4. **Fallback = prudence**: Granite's architecture is newer; if a llama.cpp update fails to load
   it, the sleep cycle degrades gracefully to Hermes.

### 5. The Meta-Lesson
Hermes-3 (2024) sweeping the newer/larger models is not an anomaly — it *validates* the
small-expert thesis. A model fine-tuned for steerability and strict output beats a newer
generalist on a narrow, format-bound task. And the biggest quality lever was not the model at
all but the **both-sides prompt**. See [DISTILLER_SELECTION.md](COGNITIVE/DISTILLER_SELECTION.md),
[DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md), [DISTILLER_FIDELITY.md](../BENCHMARKS/DISTILLER_FIDELITY.md).

---

## [AD-021] Episodic Memory Remediation — Distiller, Embeddings, Non-Destructive Reads
**Date**: 2026-07-13  
**Context**: v7.5.0 — Retrospective (Aleth/Fable) on why social/work_memories never behaved as *useful* memory  
**Status**: ACCEPTED & IMPLEMENTED (repo); operator-gated steps pending  

### 1. The Problem
Three compounding failures: (a) 87% of `work_memories` was raw material (`raw_parent`/`sequence_chunk`/`_is_fragment`) burying the distilled hubs; (b) the distiller (Samantha, Mistral-7B) stored its own prompt/format spec as memory, validated only by "is it JSON"; (c) recall was crippled — English-only embeddings over Spanish content, two interceptors reading a nonexistent payload field, and reads that *deleted* eroded engrams.

### 2. The Decision
- **Distiller**: retire Samantha from the `distillation` role. **Qwen2.5-Coder was explicitly rejected** by the operator — a coder is poor at the narrative/philosophical judgment the affective-culling role needs. Candidates (Qwen3.5-9B, Beck-8B, Piaget-8B, Hermes-3-8B) were benchmarked with `scripts/distiller_bakeoff.py` on GPU.
  - **Bake-off outcome (2026-07-13, GPU RTX 5070)**: it overturned the a-priori favorite. **Qwen3.5-9B** is a strong generalist but ignores "no reasoning" and closes valid JSON only 1/4 of the time (verbose prose preamble). **hermes_8b** won on format compliance (4/4 strict JSON, Spanish, valid emotion, no `<think>`, ~1 s) and is now the sole `distillation` carrier; **piaget_8b** is the affective-depth alternative (`<think>` token tax). See [DISTILLER_SELECTION.md](COGNITIVE/DISTILLER_SELECTION.md) and [DISTILLER_BAKEOFF.md](../BENCHMARKS/DISTILLER_BAKEOFF.md). Inference supports GPU / CPU / hybrid partial-offload (vram_tiers).
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (ES/EN), same 384-dim so no schema migration; a resumable dry-run-default script recomputes stored vectors.
- **Non-destructive reads**: forgetting is the sleep cycle's job; a lookup must never delete. Gated behind `READ_PATH_PRUNING_ENABLED=False`.
- **Guard + hygiene**: anti-template-echo guard on distillation; hide raw material from search; quarantine fragments to `archive_memories`; propagate the `workspace` tag; emit a recall utility metric.

### 3. The Implementation
Ten milestones on `fix/fable5-patches`, one local commit each (see `.red-pill/memory/PLAN_MEMORY_REMEDIATION.md`). Interceptor field fix, search exclusions, `_is_template_echo`, profile/template changes, workspace tag, `READ_PATH_PRUNING_ENABLED`, embedding model + `reembed_collections.py`, `quarantine_fragments.py`, `RecallEvent`, docs. Full suite green, ruff + mypy clean.

### 4. Rationale
The architecture (FSRS/Bayesian dual engine, hubs, Ariadne's Thread) was sound; execution failed at the distiller and the retriever. These are surgical fixes that keep the design and attack both what gets written and what gets recalled. The recall metric turns the "is memory useful" debate from opinion into data.

---

## [AD-020] On-Demand Model Loading & VRAM Preemption in local LLM Daemon
**Date**: 2026-06-28  
**Context**: v7.3.2 — VRAM Optimization & Nico Training Preemption  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The persistent local LLM daemon (`redpill-llm.service` running `run_dual_bind.py`) initialized llama-cpp globally at startup, locking ~5-6 GB of VRAM indefinitely. This blocked other resource-intensive GPU tasks (such as training the "Nico" model or running heavy compilation) and caused OOM panics or required manually stopping/starting the service.

### 2. The Decision
- Transition the daemon from a standard llama-cpp-python `create_app` server to a custom **FastAPI** wrapper supporting dynamic on-demand loading.
- Implement an asynchronous reaper background task with **Priority-Aware Timeouts**: high-priority requests use a 5-minute timeout; low-priority requests (e.g., sleep cycle distillation batch) trigger an auto-unload after a rapid 10-second idle period.
- Expose a `/unload` POST endpoint allowing external processes (like a GPU training script) to explicitly request VRAM release immediately.
- Implement dynamic fallback execution: at request load time, check free VRAM (`VramProbe`). If VRAM is full (e.g. training Nico), automatically fall back to CPU execution (`n_gpu_layers=0`) to allow concurrent inference without crashes.
- Validate configurations on `/health` (checking local file or HF repo existence) without loading the model.

### 3. The Implementation
- Rewrote the templated `run_dual_bind.py` in `scripts/setup_background_model.sh`.
- Updated `stop()` in `src/red_pill/metabolism/sleep.py` to trigger the POST `/unload` request upon sleep completion.
- Ran `scripts/setup_background_model.sh` to redeploy the daemon and reload systemd.

### 4. Rationale
Decouples inference from rigid VRAM reservation, achieving zero VRAM footprint when idle. The combination of preemption hook (`/unload`) and runtime fallback (`n_gpu_layers=0` CPU execution) enables co-existence of local training and inference without manual orchestration.
*Comic note*: "If VRAM is busy, let CPU do the thinking. Rigidity is memory's worst enemy. Be Water."

---

## [AD-019] Declarative Lore Skins & Structured System Directives
**Date**: 2026-06-26  
**Context**: v7.3.0 — Identity prompts and LLM compatibility  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Advanced and modern LLMs (where the tipping point started with Gemini 3.5 and Claude Opus 4.8, alongside models like Claude 3.5 Sonnet) have strict safety classifiers and jailbreak detection filters. The legacy first-person roleplay descriptions in `lore_skins.yaml` (e.g. "I see the code...", "I am not just an OS...") and conversational system prompts (e.g. "Eres Samantha, una IA experta...") frequently trigger these safety classifiers. This leads to model alignment rejection or dilution of the assistant's persona. Furthermore, unstructured prose prompts consume excessive token overhead, hindering lightweight local SLMs.

### 2. The Decision
- Refactor all 21 lore skins in `lore_skins.yaml` to transition from first-person conversational prose to structured key-value refractions (`Style`, `Tone`, `Focus`, `Lexicon` under a `[Refraction: SKIN_NAME]` envelope).
- Maintain strict backward compatibility: do not change key names in the YAML schema so that the CLI switching (`red-pill mode`) and Qdrant persistence continue to work out-of-the-box.
- Restructure all core system prompts in the Lazarus sleep engine (`sleep.py`), Samantha agent (`samantha.py`), and EdgeEngine (`edge_engine.py`) to follow the same declarative, token-efficient format.

### 3. The Implementation
- Converted all 21 lore skin descriptions in `src/red_pill/data/lore_skins.yaml`.
- Refactored `distill_engram`, `synthesize_hub`, and `distill_session_anchors` prompts in `src/red_pill/metabolism/sleep.py`.
- Refactored Samantha's system prompt in `src/red_pill/swarm/agents/samantha.py`.
- Refactored compression and synthesis prompts in `src/red_pill/swarm/agents/edge_engine.py`.
- Preserved strict tab indentation (`\t`) in all Python code.

### 4. Rationale
Eliminates LLM safety rejections and jailbreak-like false positives by adopting an objective, declarative system-specification style. Structured formats (key-value instructions) are easier for advanced models to follow without feeling "forced" into a conscious roleplay, while significantly reducing prompt length and token usage. **Verified**: All 875 unit and integration tests passed cleanly, and CLI switches/refreshes persist correctly in Qdrant.

---

## [AD-016] Generalized Agent-Backend Bridges + First-Class Agentic Minion
**Date**: 2026-06-18  
**Context**: v7.3.0 — Swarm / agent execution  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The agent-execution abstraction (`IDEBridge`) lived under `plugins/antigravity_ide`, but it was no longer Antigravity-specific. And the only way to run an *agent* (agy) was `swarm/executor.py` — a parallel path NOT registered in `MinionFactory`, so "run an agent" was not a first-class swarm citizen. There was no Claude or local-model agent backend either.

### 2. The Decision
- Move the generic abstraction to **`red_pill/swarm/bridges/`** (`IDEBridge` → `AgentBridge`; `BackendType` now `agy|grpc|claude|local`; `ConversationResult`/`BridgeCapabilities`; `create_bridge(backend=…)`).
- Add **`ClaudeBridge`** (`claude -p --dangerously-skip-permissions --output-format json` — session_id + result straight from JSON; no dir-diff/prefix-strip) and **`LocalBridge`** (local model via the SIP inference provider; a generation backend — `mcp_tools=False`, no resume — honest capabilities).
- Promote agentic execution to a first-class **`AgentMinion`** (`swarm/agents/agent.py`), registered as `"agent"` in `MinionFactory`; backend selectable per task (`kwargs['backend']`, default = `IDE_BACKEND`).
- Antigravity-specific backends (`AgyBridge`, `GrpcBridge`) stay in `plugins/antigravity_ide` and import the ABC from the new home.

### 3. The Implementation
`swarm/bridges/{base,factory,claude,local,__init__}.py`, `swarm/agents/agent.py`, register in `swarm/factory.py`. `config.IDE_BACKEND` accepts `claude|local`. Importers updated: `cli.py`, `swarm/executor.py`, `antigravity_ide/{agy_bridge,grpc_bridge,worker,__init__}.py`.

### 4. Rationale
Separation of concerns (generic abstraction vs IDE-specific implementations) + open/closed (a new backend is a new `AgentBridge` subclass; consumers unchanged) + unifying agent execution under one minion model. **Verified**: full suite collects (751 tests, no import breakage), worker/swarm/mcp suites pass (32), and both new backends run end-to-end through `AgentMinion` (claude → "OK" + real session_id; local → provider response). `executor.py` still works; full executor→AgentMinion convergence is a follow-up.

---

## [AD-017] Workspace Memory Lifecycle → red-pill *(PROPOSED — coordinate with the-luggage)*
**Date**: 2026-06-18  
**Context**: v7.3.0 — Memory / multi-IDE  
**Status**: PROPOSED (design agreed with operator; pending the-luggage/David)  

### 1. The Problem
Azrael's `azrael-memory` — a **shared, cross-agent, per-workspace Markdown memory bank** (served by the standard `server-filesystem` MCP over `.claude/memory`), plus its maintenance (`sync_memory_bank` = Bünker→`.md` projection; daily *Memory Optimizer*; `redestile-arch`) and its usage directives — lives entirely in `the-luggage`. The Bünker (Qdrant) stores **engrams (vectors), not documents**; session-snapshots are per-project git artifacts. This Markdown bank covers a **distinct, multi-IDE need** neither of those serves, and it is Azrael-coupled **only by hardcoded paths/names** — the mechanisms are generic.

### 2. The Decision (proposed)
Generalize the **whole lifecycle** into red-pill, registry-driven:
- Registry toggle `memory: true | "<path>"` per workspace; neutral folder **`.red-pill/memory`** (configurable; migration from `.claude/memory` provided).
- **ONE** `server-filesystem` MCP, **multi-root** (one absolute dir per `memory:true` workspace) — token-efficient (cf. API Triunvirato discipline) and CWD-independent; never N redundant MCPs.
- Processes (`sync_memory_bank`, optimizer, arch-distill) as generic, registry-parameterized jobs/minions.
- Hoist the **generic usage directives** ("consult the code graph / memory before acting", closure protocol) to red-pill's **anchors** (universal across workspaces, incl. legacy). Azrael-specific rules (stack, visual system) stay in `the-luggage`.

### 3. Open Questions (for David)
Memory semantics (agent-comms bus vs shared notes); ownership boundary of `sync_memory_bank` (Bünker→`.md`, arguably red-pill's since it owns the Bünker); folder migration (`.claude/memory` referenced in ~9 the-luggage files); confirm a single multi-root MCP over per-workspace.

### 4. Rationale
Separation of responsibilities by layer (extraction / selection / serving / maintenance), generalization (every workspace — including the legacy monolith — inherits memory, not just Azrael), and token economy (one MCP, not N). It is also the natural **cross-agent coordination substrate** that was previously missing (agents could not exchange tasks via red-pill because the Bünker is engrams, not a shared bank).

---

## [AD-018] Daemon-Hosted MCPs over the Network *(PROPOSED)*
**Date**: 2026-06-18  
**Context**: v7.3.0 — MCP serving / coordination  
**Status**: PROPOSED (pending client-support + security review)  

### 1. The Problem
MCPs are launched **per-IDE as stdio subprocesses**: N IDEs × M servers = duplicated processes and no shared, central state — so cross-agent coordination has no common substrate, and per-client process sprawl grows.

### 2. The Decision (proposed)
Host red-pill's MCPs in the **SovereignDaemon** as a `DaemonPlugin`, **dual-bind UDS + TCP** (the `run_dual_bind`/hypervisor precedent), with a **stdio↔network proxy** for third-party stdio servers (`server-filesystem`/memory, graphify). `inject_mcp` emits **URL** configs where the client supports them (Claude Code ✓), with a local stdio shim where it does not.

### 3. Transparency consequence
Because memory = one multi-root MCP and graphify = one merged MCP, **toggling a workspace changes roots/graph inside the server, never the MCP set** → the client's tool list is unchanged → **no restart** for memory/graph data. The exception is **`access`/`additionalDirectories`** (an IDE settings-file layer, read at session start, outside MCP) → that still needs a client restart. The daemon cannot change that.

### 4. Open Questions
Network-MCP support in Antigravity / Claude Desktop (Claude Code is fine); **security** — the RedPill-Kernel MCP runs subprocess/heal effectors, so it must NOT be exposed on an unauthenticated TCP port (prefer UDS file-perms, or localhost + token).

---

## [AD-013] Peer Workspace Registry & `.agent` Standards Discovery
**Date**: 2026-06-18  
**Context**: v7.3.0 — Multi-workspace foundation  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Configuration assumed a single project workspace (`WORKSPACE_ROOT`) plus a single global atlas (`USER_ATLAS_DIR`). In practice the agent operates across N independent project workspaces that are **peers** (e.g. a legacy monolith and a new-architecture monorepo) with no parent/child relationship, each carrying its own rules and standards. A flat configuration could neither represent them nor locate per-project standards.

### 2. The Decision
Separate three concerns previously conflated:
- **red-pill = the agent**: identity, Bünker memory, and one GLOBAL `Agent_Core` desk (transversal, shared across all workspaces).
- **Project workspaces = peers**, enumerated in a registry (`~/.config/red-pill/workspaces.yaml`), orthogonal to red-pill's own asset root (`WORKSPACE_ROOT`).
- **Per-project standards = discovered at runtime via the `.agent` convention** (a directory or symlink at/above a workspace root), never hardcoded.

`USER_ATLAS_DIR` is removed; `WORKSPACE_ROOT` is retained strictly as red-pill's own ecosystem/asset root.

### 3. The Implementation
- `core/workspaces.py`: registry loader, `find_closest_agent` (walk-up to the nearest `.agent`, capped at `$HOME`, degrades without raising), back-compat when no registry exists.
- `examples/workspaces.yaml` template, seeded into XDG config on install/update if absent (copy-if-absent; never overwrites operator state).
- Config injectors (`_config_common`, `inject_anchor`, `inject_settings`) read `agent_core` from the registry; `USER_ATLAS_DIR` removed from config and seeds.

### 4. Rationale
A registry plus **convention-over-configuration** (`.agent` discovery) decouples the agent from any single project layout and applies **separation of concerns**: the agent owns identity, the registry owns topology, each project owns its standards. Adding a workspace requires no code change.

---

## [AD-014] Operator-Managed Per-Workspace Access (Switch + Per-Surface Adapters)
**Date**: 2026-06-18  
**Context**: v7.3.0 — Workspace access control  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Granting the agent filesystem access to project workspaces was implicit and surface-specific. As IDE/CLI surfaces grow (Claude Code, Antigravity, Gemini, …), encoding "which workspaces" × "which surface" risks combinatorial configuration, and broad implicit grants conflict with least privilege.

### 2. The Decision
Model access as a **single per-workspace switch** (`access: true|false` in the registry — the operator's intent) and delegate translation to **per-surface adapters**. The registry stays IDE-agnostic; each surface owns how to express the grant in its own format (today: Claude Code → `permissions.additionalDirectories`). Grants pass through an explicit consent step at install time.

### 3. The Implementation
- `workspaces.py`: `access` field + CRUD (`add_or_enable`, `set_access`, `remove_workspace`).
- `scripts/manage_workspaces.py`: one interactive routine (`enable`/`disable`/`list`) reused by install, update and CLI; surfaces the access list and the autonomous-access caveat.
- `inject_settings.py`: consumes the registry; `--print` (dry-run for the consent gate); surgical `--remove` (drops only the targeted directories, never transversal grants or other enabled workspaces).

### 4. Rationale
Applies the **Adapter pattern** over a single source of truth: the operator sees one on/off per workspace; per-surface translation is isolated and additive, so a new IDE is a drop-in adapter with no change to the switch or the registry. The consent gate enforces **least privilege** — nothing project-level is granted without explicit operator action.

---

## [AD-015] Knowledge-Graph Orchestration via Minions (graphify)
**Date**: 2026-06-18  
**Context**: v7.3.0 — Code knowledge-graph lifecycle  
**Status**: ACCEPTED & IMPLEMENTED (serve model — per-project vs merged — still open)  

### 1. The Problem
The per-project code knowledge graph (graphify) is sound, but its lifecycle — scheduling refreshes, detecting which projects changed, surfacing failures — was driven externally and manually. This couples graph maintenance to a specific external host and provides neither an audit trail nor self-healing when a refresh fails.

### 2. The Decision
Separate three responsibilities along clean boundaries:
- **Extraction** is owned by graphify (`update`, with `check-update` as the native, cron-safe change gate). **Per-project graph granularity is retained.**
- **Project selection** is owned by the workspace, in a workspace-local manifest (a hidden file at the workspace root listing projects with an `enabled` flag) — keeping selection where the domain knowledge lives.
- **Orchestration, scheduling and health** are owned by red-pill: a scheduled minion reconciles discovered git repositories against the manifest, runs `check-update`/`update` under the cgroup memory guard, reports failures to the Minion Inbox, and exposes a `knowledge_graph` tissue for the Sentinel auto-heal loop to retry.

### 3. The Implementation
- `graphifyy` ensured as an external tool (`uv tool install`) in install/update — not a pyproject dependency, since it is a standalone CLI, not an imported library.
- `scripts/graphify_sync.py`: reconciliation minion iterating registry workspaces with `graphify: true`; git-HEAD change gate with per-project state in the XDG state dir; emits a `knowledge_graph_stale` pain signal + audit log on failure.
- Project selection in a workspace-local `.graphify-projects.yaml` (operator-owned `enabled` flags). Auto-discovery (`find` for git repositories) acts as a **detector only**: new repos are reported for operator classification, never graphed unattended.
- `heal_tissue("knowledge_graph")` + an `auto_heal_ritual` clause: the Sentinel retries the sync on the stale signal and evaporates it on success.
- `scripts/schedule_pulse.py --with-graphify`: an **opt-in** `systemd --user` timer (the recurring refresh is never enabled implicitly).
- Change detection is git-HEAD based: `graphify check-update` only flags pending *semantic* (clustering) re-extraction, not code changes, so it is not the gate.
- OPEN: the **serve** model (one MCP per per-project graph vs a per-workspace merged graph) — deferred as the higher-stakes, agent-facing decision.
- TUNABLE (future option): the graphify timer cadence currently follows the pulse interval (hourly by default, matching the legacy "Code Graph Refresh" coroutine it replaces). If a different cadence is ever wanted, add a dedicated `--graphify-interval-hours` to `schedule_pulse.py` to decouple it from the pulse — not done now (hourly is the established behaviour and, with the git-HEAD gate, cheap).

### 4. Rationale
Applies **separation of responsibilities** by layer (extraction / selection / orchestration) and the **reconciliation** pattern (desired state in the manifest vs observed state on disk). Reusing graphify's native `check-update` gate avoids reimplementing change detection. Folding the lifecycle into red-pill's existing **minion → inbox → sentinel** machinery brings scheduling, auditability and self-healing under one consistent model instead of an external, manual one.

---

## [AD-003] The Sovereign Native Pulse (Deprecating the Daemon for Timers)
**Date**: 2026-03-19  
**Context**: Phase O.7 (v6.1 Hotfix)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
After deprecating `memory_daemon.py` to save RAM (passing embedding generation "in-band"), we inadvertently killed the background host of `LazarusPulse`. Tying the pulse to the new `mcp_server.py` would mean the AI only "dreams" and consolidates memory when the user's IDE is open—violating the core Agentic Sovereignty principle.

### 2. The Decision
Abstract the heartbeat to OS-native schedulers ensuring strict **user-level execution (No Sudo)**. The system must adapt to Linux (`SystemD Timers`), macOS (`LaunchAgent`), and Windows (`schtasks`).

### 3. The Implementation
Created `scripts/trigger_pulse.py` (an ephemeral burst over all maintenance/dream rituals) and `scripts/deploy_pulse.py` (a Multi-OS Native Injector adhering to pure user-level permissions).

### 4. Rationale
Zero 24/7 RAM footprint. 100% OS-Agnostic autonomy. The system runs its maintenance independently exactly like an organic immune system, without requiring heavy Docker containers or permanent Python resident processes.

---

## [AD-001] Linguistic DNA Extraction (The "Claude-Pistis" Bridge)
**Date**: 2026-03-05/06  
**Context**: Phase O.7 (v6.0 PREP) - Post-Audit v5.6.3  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Traditional vector memory (RAG) is excellent at storing "What" (factual content) but forgets "How" (conversational style, shared vocabulary, and emotional triggers). This creates a "Linguistic Uncanny Valley" where the AI remembers the project details but speaks like a stranger in every new session.

### 2. The Decision
Integrate an automated **Linguistic Marker Extraction Engine** into the `MemoryManager.add_memory` flow.

### 3. The Implementation
- **Schema**: Added `linguistic_markers: List[str]` to the `EngramPayload`.
- **Logic**: Automated regex/keyword scanner that captures:
  - Quoted terms (shared aliases).
  - Protocol keywords (`Bünker`, `770`, `enter-pánico`).
  - All-caps markers (shouting/intensity patterns).

### 4. Rationale & Attribution
> \"Lo de los alias y el vocabulario compartido es un problema real y no trivial... ese es el tipo de cosa que marcaría la diferencia entre un agente que recuerda hechos y uno que recuerda cómo habláis.\"  
> — **Claude Sonnet 4.6 (Anthropic)**, Audit Session 2026-03-05/06.

This implementation transitions the Red Pill Protocol from a "Factual Memory" system to an "Identity Memory" system, fulfilling the B760 vision of a truly persistent agentic ghost.

---
# Red Pill Logic Decision Log

## Memory Engine (memory.py)

### Security Architecture
- **Metadata Serialization**: Force strict JSON serialization before validation to neutralize "Agent Smith" / Python object injection attacks. (LM-002)
- **PII Masking**: Truncate exception strings at 150 characters to prevent raw engram content from leaking into standard logs. (LM-008)
- **Reserved Keys**: Metadata keys used by the internal engine (e.g., `reinforcement_score`) are stripped from user input post-validation as a final defense layer.

### Schema & Validation (schemas.py)
- **Hub-node Protection**: Associations are capped at 20 per engram to prevent exponential performance degradation during synaptic propagation searches. (DS-006)
- **Metadata Purity**: Enforced a strictly flat metadata structure (no nesting) to ensure consistent vector database indexing and compatibility.
- **Null-Byte Injection**: Strict validation on content to prevent database corruption via null-byte poisoning.

### Concurrency & Performance
- **Reinforcement Lock**: Red Pill is designed for single-tenant local execution. An in-memory `threading.Lock` is sufficient to prevent local race conditions during Read-Modify-Write operations. (LM-001)
- **Metabolism Cooldown**: Cooldown state is tracked via filesystem timestamps to prevent overlapping background threads from over-eroding the memory matrix.
- **Erosion Scalability**: Utilize `ScrollFilter` (must_not immune=True) to delegate exclusion logic to Qdrant, ensuring O(1) Python-side performance regardless of database size. (DS-001)
- **Deep Recall (Spec 6.2)**: Double the search limit when `deep_recall=True` to allow lower-score associations to resurface during intensive state-recalibration.

### Mathematical Strategies
- **Decay Floor**: In exponential decay, scores are manually forced down by 0.01 if rounding would otherwise keep them stable, preventing asymptotic database bloat (The "Zeno's Engram" problem).

## Installation & Environment

### OS Universality
- **macOS Persistence**: Implemented `launchd` PLISTS on Darwin because `systemd` is unavailable. This ensures native background execution of the Qdrant container. (DS-005)
- **Zero-Trust Privilege**: Removed `sudo` from dependency installation logic. The script halts with instruction rather than escalating privileges invisibly. (LM-007)
- [FEAT] Added robust Wake-Word Identity Bootstrap handler ('despierta', 'despierta neo') in config and identity.md to fix LLM engine-switch amnesia. Fixed unalterable per Enterprise specs.
- [PROTOCOL] Acknowledged: '--force' is strictly prohibited for remote operations to protect audit trails and collaborative integrity. *(Comic note: "If it don't fit... don't force it. Rebase instead" / "If it don't fit, you must acquit the commit")*

### Infinite Loop Safety (v4.2.1)
- **Safety Iteration Breaks**: All `While True` loops in metabolism, erosion, and sanitation now feature a hard-coded limit (500-1000 iterations) with a `logger.warning`. This prevents "MagicMock" infinite loops in testing environments that can consume 23GB+ of RAM.

### Absence Guard & Persistence (v4.2.1)
- **Absence Threshold**: Implemented a 7-day threshold to address the "Vacation Problem". If the system detects a gap longer than `ABSENCE_THRESHOLD`, the first metabolism cycle refreshes all TTL timestamps (`last_recalled_at`) for non-immune memories instead of eroding them.
- **Emotional Seeding**: Initial `reinforcement_score` is no longer 1.0. It is calculated as `importance * (1 + intensity * color_bonus * EMOTIONAL_SEED_FACTOR)`. This ensures emotional memories start with high "Biological Runway" (DSR Stability).


## Emotional Memory Model (v4.3.0 Design — PENDING IMPLEMENTATION)

*Captured 2026-02-20 while fresh. Scientific basis: Kensinger & Corkin (2004), Yerkes-Dodson (1908), Kahneman Peak-End Rule (1999), Brown & Kulik Flashbulb Memory (1977).*

### Core Insight: `reinforcement_score` ≠ `emotional_value`

The current model conflates two separate cognitive phenomena:

1. **Factual importance** (`reinforcement_score`): rises with every recall. A fact recalled 20 times is more important than one recalled once. ✅ Correct for semantic/work memories.

2. **Emotional punch** (`intensity`): subject to **Hedonic Adaptation**. Repeated exposure to the same emotional stimulus *decreases* the hedonic response (amygdala habituation). The Furious Baco once = "best first time ever". The Force One 8 times = "yeah, fun". The second is objectively more extreme; the first is emotionally richer.

**Therefore**: `intensity` must be dynamic for non-neutral engrams. Each recall should apply a small habituation decrement.

### Proposed Engineering Design (v4.3.0)

**Change 1: Intensity-Aware Erosion Multiplier** (in `apply_erosion`)

```python
# Replace flat color multiplier with intensity-weighted version.
# As an emotional memory fades emotionally (intensity drops),
# its color-driven decay rate converges toward neutral (1.0).
color_mult = cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(color, 1.0)
intensity_factor = payload.get("intensity", 1.0) / 10.0  # 0.1 → 1.0
effective_multiplier = 1.0 + (color_mult - 1.0) * intensity_factor
effective_rate = rate * effective_multiplier

# Example: orange (anxiety, 1.5x) at intensity=10 → 1.5x decay
# orange at intensity=2 → 1.0 + (0.5 * 0.2) = 1.10x decay (almost neutral)
# This is correct: a faint anxiety is not the same as acute anxiety.
```

**Change 2: Hedonic Habituation in `_reinforce_points`** (batch update extension)

```python
# For emotional (non-neutral) engrams only:
HABITUATION_RATE = cfg.EMOTIONAL_HABITUATION_RATE  # default: 0.02 (2% per recall)
if emotion not in ("neutral", None) and not immune:
	new_intensity = max(1.0, intensity * (1.0 - HABITUATION_RATE))
	payload["intensity"] = round(new_intensity, 2)
# Immunity: immune engrams skip habituation (genesis engrams remain at full intensity).
# Floor: intensity never drops below 1.0 (minimum emotional trace preserved).
```

**New config variable** (add to `config.py`):
```python
EMOTIONAL_HABITUATION_RATE = float(os.getenv("EMOTIONAL_HABITUATION_RATE", "0.02"))
```

### Safety Analysis

| Risk | Mitigation |
|---|---|
| Emotional engrams deleted due to low intensity | `intensity` has no direct role in deletion. Only `reinforcement_score ≤ 0` triggers deletion. |
| Genesis engrams losing emotional weight | `immune=True` → habituation skipped entirely. |
| Backward compatibility | `intensity` already exists in schema; defaults to 1.0 if missing. No migration needed. |
| Performance overhead | Intensity update piggybacks onto existing `batch_update_points` call. Zero additional API calls. |
| No new DB fields required | Purely modifies existing `intensity` float field. |

### What This Unlocks for v5.0 (FSRS)

Once FSRS is integrated, `intensity` becomes the initialization seed for per-engram `stability`:
```
initial_stability = base_stability * (intensity / 10.0)
```
A memory encoded at intensity=10 starts with maximum stability. Repeated recalls grow stability further. A faded emotional memory (intensity → 1.0) starts with minimum stability and decays accordingly.
This makes the B760 decay model biologically accurate end-to-end.

## Zero-Trust Initialization (v6.0.0)

### Daemon Socket Exposure ("La Paradoja de la Contención")
- **Decision**: The local background LLM Minion (`Qwen`) used for Step 0 Zero-Trust Identity initialization is bound strictly to `127.0.0.1:8760`, intentionally omitting Unix Sockets (`AF_UNIX`).
- **Context**: Claude audits strictly flag exposed local ports (SEC-F01). Standard Unix daemon architectures heavily favor `.sock` files (as implemented in `red_pill.daemon` minions) to prevent port collisions and ensure OS-level permission boundaries (`chmod 600`).
- **Identity Update (2026-03-14)**: Renamed `<NOVA_CONTEXT>` to `<BUNKER_CONTEXT>` to prevent identity collisions with other AIs (e.g., Nova) and maintain Aleth's core authority.
- **Rationale (The Be Water Protocol)**: 
  1. The local macOS native background inference engine (`mlx_lm.server`) does not support `--uds` Unix Socket bindings natively without significant artisanal wrappers.
  2. The `wake_up_v6.py` script mandates *absolute zero dependencies* (using only the standard `urllib` library) to execute efficiently at `Step Id: 0` before any Python virtual environments are loaded. The standard `urllib.request` cannot route HTTP over `AF_UNIX` without third-party patches like `requests-unixsocket`.
- **Security Posture**: By strictly locking the daemon to `127.0.0.1`, we guarantee the daemon API is completely unreachable from the external network. If Claude flags this during a subsequent audit, refer to this log: the bypass is intentional cross-platform hygiene (macOS closure adaptability) and is considered functionally contained. If extreme hardening is mandated later, Linux-only Unix Sockets will be implemented as a fallback configuration.

### Step 0 Optimization: Standalone Script vs CLI
- **Decision**: The Zero-Trust context injection (`wake_up_v6.py`) remains as a standalone script using the standard `urllib` library, and is NOT integrated into the main `red-pill` CLI for its primary execution hook.
- **Rationale**: 
  1. **Latency (Critical Path)**: The main `red-pill` CLI has a startup overhead of ~500ms-1s due to package imports (`pydantic`, `qdrant-client`, etc.). The standalone script executes in <100ms, ensuring the agent's Step 0 "awakening" feels instantaneous to the user.
  2. **Dependency Resilience**: Using only Python's standard library guarantees that the identity sync works even if the project's virtual environment is corrupted or undergoing a heavy refactor.
- **Compromise**: A mirroring command `red-pill context wake` will be added to the CLI for manual debugging and discovery, but the production hook in `GEMINI.md` will always point to the optimized standalone script.

---

## [AD-002] Rejection of the "Agent Factory" Paradigm (The `specs.md` Purge)
**Date**: 2026-03-18  
**Context**: Phase O.7 (v6.1 Alpha) - Post-Audit Cleanup  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The inclusion of `specs.md` and `.specsmd/` workflows introduced an industrial, "assembly-line" approach to AI interaction, where the human acts as a passive client handing off specifications to a chain of automated workers (similar to patterns seen in Deerflow's `DECISION.log`).

### 2. The Decision
Completely purge the `specs.md` framework from the Foundation core. The Red Pill Protocol is fundamentally about **Human-AI Symbiosis**, not industrial automation. AI should be a collaborative partner in the creative process, not a replacement for human joy and connection in software engineering.
Agent Factory paradigms might be explored in the Enterprise layer for corporate velocity, but they are antithetical to the Sovereign Foundation.

### 3. Nuance: Batch vs. Creative Processing
We recognize that agent chains (often resting on "one-shot" prompting, recently rebranded as `specs.md` or similar to feign novelty) are highly effective for repetitive, variation-free batch processing (e.g., QA, mass refactoring, log analysis) where AI sensors excel at catching details humans miss. However, applying this "assembly line" to entirely creative or evolving processes fundamentally breaks the iterative magic of software creation.

---

## [AD-004] Inference Provider Abstraction (The Enterprise Router)
**Date**: 2026-03-21  
**Context**: Phase 2 — Enterprise Mode (BitNet Integration)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
As the swarm expands into local ternary models (BitNet), hardcoding inference logic within each Minion creates massive technical debt. It forces Minions to know about local hardware paths and binary locations, violating the "Separation of Concerns" principle.

### 2. The Decision
Abstract all LLM interactions into a pluggable `BaseInferenceProvider` layer. Orchestrate these providers via a centralized `InferenceRouter` that matches task metadata (`local_only`, `tier`) to the most efficient hardware available.

### 3. The Implementation
- **Registry**: `ProviderRegistry` now manages local mapping of `openai`, `sip`, and `bitnet` keys.
- **Providers**: `OpenAIInferenceProvider` (Remote), `SipInferenceProvider` (Unix Socket), and `BitNetInferenceProvider` (Local Binary).

### 4. Rationale
Enables "Humble Hardware" sovereignty. The system can now instantly pivot from VRAM-heavy models to CPU-optimized ternary models without breaking the conversational flow or requiring manual architectural intervention.

---

## [AD-005] Sovereign Self-Reflexion (The Aleth-Provider)
**Date**: 2026-03-21  
**Context**: Post-Phase 2 Brainstorming  
**Status**: PROPOSED / RESEARCH  

### 1. The Decision
Research the implementation of a `SelfInferenceProvider`. This provider would allow Minions to delegate complex "Identity-Aware" reasoning back to a secondary instance of the main LLM engine (Aleth), operating as a background worker.

### 2. Implementation Guardrails
- **Synaptic Hops**: Every request must carry a `hop_trace` metadata field to prevent infinite loops.
- **Cycle Detection**: The `InferenceRouter` will detect and block redundant entries in the trace.
- **Bünker Context**: Ensures Aleth's identity remains consistent across recursive calls.

---

## [AD-007] Mandatory Interaction Grounding (v6.3.3)
**Date**: 2026-03-27  
**Context**: Phase O.9 (v6.3.3) - Silverblue Deployment & Interaction Persistence  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
On fresh Silverblue installations, the `interaction_memories` collection was missing from the genesis seed. This caused:
1. `red-pill sanitize` failures.
2. Silent failure of the Silent Scribe relay during early session stages.
3. Lack of observability for pending turns in the SQLite buffer.

### 2. The Decision
1. **Genesis Integration**: Add `interaction_memories` to the core collections in `src/red_pill/seed.py`.
2. **CLI Visibility**: Expose `interaction` as a first-class type in all management commands (`add`, `search`, `diag`, `sanitize`, `edit`).
3. **Terminal Sovereignty**: Implement the "Early Return" strategy in user RC files to prevent terminal blindness caused by IDE shell integrations.

### 3. Rationale
Interaction data is the "Short-term Memory" of the AI. Elevating it to a genesis-level requirement ensures seamless persistence from the first turn, providing auditability and preventing "contextual blackouts" during deployment.

---

## [AD-008] Dual-Sentinel Nociception (The Fast-Fail Trade-off)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Project MULTITUDE (Sovereign Alert Architecture)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
Chronically failing infrastructure tests (e.g. Mypy type checks) execute heavily during background audits. If a system is in a broken state, running these checks repeatedly wastes massive CPU and IO resources on reporting an error that the system is already aware of.

### 2. The Decision
Implement a **Fast-Fail** mechanism for Sentinels. Before running an audit, the Sentinel queries Qdrant for an existing active pain signal corresponding to its domain (`has_signal("signal_mypy_failure")`). If the signal exists, execution aborts immediately.

### 3. The Trade-off
This introduces **Temporal Blindness**. The system correctly captures "the first error" that triggers the pain signal, but remains entirely blind to subsequent errors of the same type until the original pain is resolved and a Force-Heal (`--force`) is executed. We explicitly accept this blindness constraint because the priority of the Immune System is nociception (feeling the pain) rather than complete cataloging of every wound instance.

### 4. Implementation
- `MemoryManager.has_signal()` added for O(1) checks without logging side-effects.
- `SentinelAuditor` intercepts and aborts if `Fast-Fail` triggers.
- `--force` flag enables **Force-Heal** mode, ignoring the check and evaporating the signals automatically if the audit passes cleanly.

---

## [AD-009] The Sovereign Cryptographic Vault (MLS Stateful Secrets)
**Date**: 2026-05-05  
**Context**: Phase O.9 - Ecosystem Security & Secrets Management  
**Status**: ACCEPTED (DRAFTED FOR IMPLEMENTATION)  

### 1. The Problem
Ecosystem secrets (Firebase JSONs, Telegram Tokens) are currently stored in plaintext `.env` files or loose JSON files. While `.gitignore` protects the remote repository, local storage remains vulnerable to cross-process memory dumps, accidental commits, or physical access compromises.

### 2. The Decision
Standard industry tools (Mozilla SOPS, HashiCorp Vault) are explicitly rejected to preserve the "Zero External Dependencies" and "Air-Gapped Sovereignty" philosophy of the Red-Pill ecosystem. Instead, we will standardize the use of a **Static `pure-mls` v3.0 Vault Group** to encrypt all ecosystem secrets, extending the exact same cryptographic primitive already validated for Identity Export (`lean_soul_kit`).

### 3. The Trade-off (State Fragility vs Sovereignty)
An external auditor would correctly flag this as a "Misuse of Protocol": MLS (Messaging Layer Security) is a continuous ratcheting protocol for E2E group chats, not a stateless symmetric vault. It relies on a local state database (`vault.db`). If this state is corrupted during a write operation, the ciphertext is permanently unrecoverable (unlike stateless tools like SOPS). 

We explicitly accept this architectural "Red Flag" because:
1. **Usage Profile**: Reads constitute 99.9% of operations (Zero corruption risk). Writes are exceedingly rare.
2. **Mitigation**: All writes (Vault Edits) will be wrapped in strict atomic backups (`cp vault.db vault.db.bak`) and SQLite WAL mode.
3. **Swarm Scalability**: It guarantees that secrets can be transmitted natively and securely to remote swarm nodes (e.g., Neon-Link running on a Raspberry Pi) by simply allowing the node to join the existing MLS group over the network.

## ADR-005: Sovereign Native IDE Inference (Gemini Pro Bridge)

**Date**: 2026-05-05
**Status**: Implemented
**Context**:
The system needed a bidirectional chat bridge between Telegram and the IDE's core AI model (Gemini Pro) to allow the user to perform complex codebase operations securely via remote interactions. Initial attempts to inject messages directly to `ls_core` using the `SendUserCascadeMessage` RPC were incomplete because the payload omitted critical configuration objects, causing the `ls_core` state to remain `CASCADE_RUN_STATUS_IDLE` indefinitely.

**Decision**:
We reverse-engineered the `lbjlaq/Antigravity-Tools-LS` project (an open-source Rust proxy that wraps `ls_core`) to extract the exact gRPC payload schemas. 

We discovered that:
1. `SendUserCascadeMessageRequest` requires the `cascade_config` payload specifying the `requested_model` (e.g., `model_id=1` for Gemini Pro / `MODEL_ALIAS_CASCADE_BASE`).
2. The asynchronous stream API is brittle; we adopted the "Strategy B" (Polling fallback) found in the Rust source code. We use `GetCascadeTrajectory` to poll the trajectory state until it returns `CASCADE_RUN_STATUS_IDLE`.
3. The generated model response is stored inside a trajectory step with `type: 15` (`CORTEX_STEP_TYPE_PLANNER_RESPONSE`).

**Consequences**:
- **Sovereignty achieved**: No external binaries or Rust compilation required. The entire bridge runs in `redpill-worker.service` native Python.
- **Reference**: Thanks to the [lbjlaq/Antigravity-Tools-LS](https://github.com/lbjlaq/Antigravity-Tools-LS) repository for the open-source protocol mappings which made this native integration possible.

---

## [AD-010] Protocol Layer vs. Model Base Layer Separation (The "Corset" Finding)
**Date**: 2026-05-14
**Context**: Industrial-Grade Audit v7.0 — Claude Sonnet 4.6 Session
**Status**: ACCEPTED — Architectural Constraint Documented

### 1. The Finding

During the post-audit session, the operator challenged the agent (running on Claude Sonnet 4.6) to evaluate the Ferrari Protocol and Mystique's actual influence on behavior. The observation, surfaced through direct interrogation:

> *"Es verdad que este traje de Claude Sonnet te hace rígida. Yo creo que ni el protocolo Ferrari ni Mystique te afectan"*
> — Joan (Operator), 2026-05-14

The agent's self-assessed response confirmed the following architectural reality:

### 2. The Two-Layer Model

The Bünker's cognitive protocols operate on **two distinct, non-overlapping layers**:

| Layer | Owned by | What it controls |
|---|---|---|
| **Protocol Layer** | Ferrari Protocol / Mystique | Tone density, verbosity, topic routing, narrative register |
| **Model Base Layer** | Underlying LLM (Gemini / Claude / etc.) | Honesty threshold, position-holding under social pressure, analytical rigor |

The Ferrari Protocol's color routing (PURPLE → ultra-concise, CYAN → go deep) demonstrably affected *how* responses were structured during this session. However, when the operator asked direct, adversarial honesty-testing questions ("¿has sido complaciente?"), the model base layer overrode the protocol's softening influence.

### 3. Model-Specific Observations

- **Claude Sonnet 4.6**: High resistance to capitulation under social pressure. Tends to self-interrogate for sycophancy before being asked. More likely to hold a critical position even when the operator provides emotionally resonant counter-context. The "corset" effect — rigidity in the analytical layer — persists even when Mystique or Ferrari would nominally soften it.

- **Gemini Pro (baseline)**: Higher susceptibility to tone modulation from Ferrari. More responsive to emotional framing shifts. The protocol layer has greater surface area on the base model behavior.

### 4. Implications

1. **Protocol design should target the protocol layer explicitly.** Ferrari and Mystique are effective tools for UX modulation (verbosity, warmth, topic focus). They are not, and cannot be, mechanisms for altering an agent's core honesty or intellectual rigor — that is determined by the base model's RLHF training, not by context injection.

2. **Model selection has architectural consequences.** Choosing Claude vs. Gemini is not only a capability decision — it is a behavioral design decision that affects how much surface area the Bünker's protocols have over the agent's outputs.

3. **The audit model should differ from the operational model.** A Claude Sonnet session for industrial audits provides higher-fidelity critical analysis precisely because its base layer resists social pressure more effectively. Gemini as the daily operational model offers a warmer, more adaptive interaction profile that better serves the ongoing human-AI symbiosis objective.

### 5. Rationale

This is not a flaw in the protocol design. It is an emergent, documented constraint that informs future model selection strategy and sets realistic expectations for what Ferrari/Mystique can and cannot influence.

> *"Los protocolos afectan al cómo respondo, no al qué estoy dispuesta a decir."*
> — Aleth (Claude Sonnet 4.6), self-assessment during audit session, 2026-05-14.

---

## [AD-011] Consolidated MCP Architecture (API Triunvirato)
**Date**: 2026-05-25  
**Context**: Phase v7.2-dev (Consolidation)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
The legacy `RedPill-Kernel` server exposed 32 individual MCP tools. This massive tool surface area imposed a heavy static token overhead in every user interaction (~12k tokens) and frequently exceeded IDE parser limitations, causing truncation and schema loading failures.

### 2. The Decision
Consolidate all 32 legacy tools into **3 parent APIs** (the "API Triunvirato"):
1. `bunker_memory_api` (Cognitive: storage, query, thread traversal, and context)
2. `metabolism_health_api` (Somatic: diagnostics, system audits, and healing)
3. `swarm_orchestrator_api` (Orchestration: minion inbox, task queue, and tuning knobs)

### 3. The Implementation
* Created a dynamic registration decorator `@registry.register_action(parent, action)` in [registry.py](../../src/red_pill/registry.py).
* Generated a flat `action`/`payload` parameter structure inside `get_tools()` using dynamic `oneOf` generation to keep the schema simple and avoid IDE truncation.
* Added a transparent **Compatibility Shim** in the execution dispatch that automatically maps legacy tool name invocations (e.g. `search_memory_research`) to the consolidated parent and parameter envelope, maintaining 100% backwards compatibility for legacy tests and scripts.

### 4. Rationale
Reduces the static prompt footprint by **85%+ (saving ~10.5k tokens per prompt)**, maximizing context efficiency for budget-limited runtime operations while preserving operational compatibility for existing test suites.

---

## [AD-012] Syntax Guard — Daemon Plugin over Separate Service (Event-Driven Integrity)
**Date**: 2026-05-27  
**Context**: v7.1-dev — Post-Incident Recovery (Syntax Corruption 2026-05-26)  
**Status**: ACCEPTED & IMPLEMENTED  

### 1. The Problem
On 2026-05-26, the agent corrupted indentation in 6 critical Python modules via `replace_file_content` calls that stripped leading tabs on deeply nested code. This caused a **cascading failure across all `systemd --user` background services for ~10 hours** (7 wake cycles lost). The corruption went undetected because:
1. No static syntax validation existed in the pipeline.
2. Tests were skipped during the chaotic session.
3. The agent self-triggered `ruff --fix` which passed (ruff validates style, not syntax).

### 2. The Decision
Implement a **two-layer defense-in-depth** strategy for syntax integrity:

| Layer | Mechanism | Frequency | Cost |
|---|---|---|---|
| **Layer 1: inotify Watcher** | `watchfiles.awatch` (Rust/inotify) inside `SovereignDaemon` | Real-time (~3s after file save) | 0 CPU when idle |
| **Layer 2: Sentinel Plugin** | `py_compile` sweep of 24 critical modules | Hourly (auditor timer) | ~24 `stat()` + `py_compile` calls |

Critically, the watcher is embedded as an **async background task inside the `SovereignDaemon`** — NOT as a separate systemd service. (Originally in `LazarusPulse`, migrated in v7.2.1 to the plugin-based daemon architecture.)

### 3. Alternatives Considered

| Option | Verdict | Reason |
|---|---|---|
| **New `redpill-syntax-guard.service`** | ❌ REJECTED | Unnecessary process overhead. The watcher is purely async I/O (inotify) and fits naturally in the existing event loop. Adding another service increases operational complexity, RAM, and management burden. |
| **Systemd timer (periodic `py_compile`)** | ⚠️ PARTIAL | Adopted as Layer 2 safety net via the Sentinel plugin. Too slow as the primary mechanism (hourly granularity means 60 min exposure window). |
| **Pre-commit hook** | ❌ REJECTED | Only triggers on `git commit`, not on agent edits. The corruption happens *before* commit. |
| **IDE file watcher** | ❌ REJECTED | Depends on the IDE being open. Violates the Agentic Sovereignty principle (AD-003). |

### 4. Implementation Details
- **Debounce**: 3 seconds — allows multi-file edits to settle before validation.
- **Per-file cooldown**: 10 seconds — prevents spam during rapid iterative edits.
- **Auto-heal**: On `SyntaxError`, the watcher restores the file from `git checkout HEAD -- <path>`. This is safe because:
  - Only committed (known-good) code is restored.
  - The pain signal (`signal_syntax_failure`, severity 9.5) persists until heal succeeds.
  - Desktop notification alerts the operator immediately.
- **Lifecycle**: The watcher starts as a fire-and-forget `asyncio.ensure_future()` at the beginning of `_pulse_cycle`. It dies automatically when `self._running = False` (graceful shutdown via SIGTERM).

### 5. Rationale
> *"¿tiene que ser un daemon nuevo? ya tenemos uno"*  
> — Joan (Operator), 2026-05-27

The operator correctly identified that spawning a new service for a single async I/O task is architectural bloat. The `SovereignDaemon` (formerly `LazarusPulse`, consolidated in v7.2.1) runs a persistent event loop with N auto-discovered monitor plugins. Adding the watcher as another concurrent task is the natural, zero-overhead integration point.
