# Red Pill Protocol — Documentation Index

> *Everything you need to understand, operate, extend, and feel this system.*

This is the map of `docs/`. Start here. Each link includes a one-line description of what you'll find inside.

---

## 📋 Root-level quick refs

| Document | What it is |
|----------|-----------|
| [CLI Reference](CLI_REFERENCE.md) | All `red-pill` CLI commands with usage examples |
| [ENV Reference](ENV_REFERENCE.md) | Complete `.env` parameter list — every knob and what it does |
| [Philosophy](PHILOSOPHY.md) | Sovereign trade-offs and architectural philosophy of the Protocol |

---

## ⚙️ TECHNICAL — Architecture & Specifications

Internal specs for contributors, engineers, and AI agents working on the core.

| Document | What it is |
|----------|-----------|
| [ARCHITECTURE.md](TECHNICAL/ARCHITECTURE.md) | Full system architecture — components, data flows, version overview |
| [WAR_ECONOMY.md](TECHNICAL/WAR_ECONOMY.md) | War Economy: Reuse and orchestration of system organs and components |
| [EVENT_ROUTER_ARCHITECTURE.md](TECHNICAL/EVENT_ROUTER_ARCHITECTURE.md) | Technical spec for the asynchronous Event Router and queue managers |
| [NEON_LINK_EDGE_HUB.md](TECHNICAL/NEON_LINK_EDGE_HUB.md) | Technical architecture of the Neon-Link Edge Hub middleware |
| [ANTIGRAVITY_LS_PROXY.md](TECHNICAL/ANTIGRAVITY_LS_PROXY.md) | Language Server Proxy architecture for Antigravity IDE |
| [ROADMAP.md](TECHNICAL/ROADMAP.md) | Vision, mission, backlog, and the path forward |
| [v7_PLAN.md](TECHNICAL/v7_PLAN.md) | Red Pill v7.0: Foundation & Autonomous Drive Plan |
| [DECISION_LOG.md](TECHNICAL/DECISION_LOG.md) | Record of every major architectural pivot and the reasoning behind it |
| [TESTS.md](TECHNICAL/TESTS.md) | Test suite philosophy and structure |
| [SOUND_OF_SILENCE.md](TECHNICAL/SOUND_OF_SILENCE.md) | The Python coding standard enforced by `ruff` in this project |
| [SOVEREIGN_PLUGINS.md](TECHNICAL/SOVEREIGN_PLUGINS.md) | Defining the dual-path architecture: Code vs. State separation |
| [GOVERNANCE.md](TECHNICAL/GOVERNANCE.md) | What is fixed (immune to impulse) and what is fluid (open to evolution) |

### Hardware

| Document | What it is |
|----------|-----------|
| [B760_TECHNICAL_SPEC.md](TECHNICAL/HARDWARE/B760_TECHNICAL_SPEC.md) | Hardware and system reference for the sovereign B760 build |
| [AGENT_RECOMMENDATIONS.md](TECHNICAL/HARDWARE/AGENT_RECOMMENDATIONS.md) | Hardware and model recommendations for sovereign agents |
| [BITNET_1_58_SCALING_LAWS.md](TECHNICAL/HARDWARE/BITNET_1_58_SCALING_LAWS.md) | BitNet 1.58b math: VRAM density, MatMul annihilation, Pareto frontier |
| [BITNET_BENCHMARK_STUDY.md](TECHNICAL/HARDWARE/BITNET_BENCHMARK_STUDY.md) | 1.58-bit intelligence benchmark: Zero-Shot, JSON extraction, Code Generation on RTX 5070 |
| [BITNET_QUAD_FLAVOR_REPORT.md](BENCHMARKS/BITNET_QUAD_FLAVOR_REPORT.md) | **Phoenix Edition**: Multi-backend performance report (CPU, CUDA, ROCm, NPU) |
| [MULTI_BACKEND_BENCHMARK.md](TECHNICAL/HARDWARE/MULTI_BACKEND_BENCHMARK.md) | Multi-Backend inference benchmark on AMD/NVIDIA hardware |
| [BITNET_REMEDIATION_RUNBOOK.md](TECHNICAL/BITNET_REMEDIATION_RUNBOOK.md) | Remediation runbook for BitNet CUDA inference stabilization |
| [TURBOQUANT_ROADMAP.md](TECHNICAL/HARDWARE/TURBOQUANT_ROADMAP.md) | TurboQuant KV Cache compression roadmap (QJL + PolarQuant, 2.5-3.5 bits) |

### Security

| Document | What it is |
|----------|-----------|
| [OVERVIEW.md](TECHNICAL/SECURITY/OVERVIEW.md) | **Hub**: 3-tier security philosophy (Be Water) with links to all security docs |
| [BE_WATER_SECURITY.md](TECHNICAL/SECURITY/BE_WATER_SECURITY.md) | Three-tier security sovereignty model |
| [SECURITY_STRATEGY.md](TECHNICAL/SECURITY/SECURITY_STRATEGY.md) | API key and identity recovery protocol |
| [THREAT_MODEL.md](TECHNICAL/SECURITY/THREAT_MODEL.md) | Scope, assumptions, and threat surface analysis |
| [PROMPT_INJECTION_MECANISM.md](TECHNICAL/SECURITY/PROMPT_INJECTION_MECANISM.md) | How prompt injection is detected and mitigated |
| [ANTIGRAVITY_KEY_RECOVERY.md](TECHNICAL/SECURITY/ANTIGRAVITY_KEY_RECOVERY.md) | Antigravity key recovery procedures |
| [WONTFIX.md](TECHNICAL/SECURITY/WONTFIX.md) | Known security exceptions formally acknowledged and accepted |

### Swarm

| Document | What it is |
|----------|-----------|
| [SWARM_ARCHITECTURE.md](TECHNICAL/SWARM/SWARM_ARCHITECTURE.md) | Swarm messaging technical spec (v3.0) — transport, discovery, topology, inter-agent protocol |
| [NEON_LINK_ROUTING.md](TECHNICAL/SWARM/NEON_LINK_ROUTING.md) | Neon-Link Routing Engine technical specification |
| [SWARM_INTEGRATION.md](TECHNICAL/SWARM/SWARM_INTEGRATION.md) | Guide for implementing new transports and swarm backends |
| [HIVEMIND_GOVERNANCE.md](TECHNICAL/SWARM/HIVEMIND_GOVERNANCE.md) | Data sovereignty charter and participation policy for the HiveMind open network |
| [MLS_ESTIMATION.md](TECHNICAL/SWARM/MLS_ESTIMATION.md) | MLS/TreeKEM group key agreement estimation and design |
| [EDGE_HIVE_TRANSIT_DOCK.md](TECHNICAL/SWARM/EDGE_HIVE_TRANSIT_DOCK.md) | Edge-to-HiveMind transit architecture |
| [SYNAPTIC_BRIDGE.md](TECHNICAL/SWARM/SYNAPTIC_BRIDGE.md) | Agent coordination protocol between Aleph and Nova |
| [SENTINEL_AUDITOR.md](TECHNICAL/SWARM/SENTINEL_AUDITOR.md) | Sentinel Auditor configuration and architecture |

> [!WARNING]
> **Swarm E2EE is a Proof-of-Concept.** The current MLS/TreeKEM implementation does not yet provide Perfect Forward Secrecy (PFS) or Post-Compromise Security (PCS). Production-grade MLS is planned for v7.0. See `MLS_ESTIMATION.md` for details.

### Cognitive (Research)

| Document | What it is |
|----------|-----------|
| [NEURO_SYMBOLIC_MEMORY.md](TECHNICAL/COGNITIVE/NEURO_SYMBOLIC_MEMORY.md) | Neuro-symbolic memory architecture research |
| [NEURO_IMMUNE_SYSTEM.md](TECHNICAL/COGNITIVE/NEURO_IMMUNE_SYSTEM.md) | Active immunity system design and biological analogies |
| [AFFECT_MULTIPLIERS_RESEARCH.md](TECHNICAL/COGNITIVE/AFFECT_MULTIPLIERS_RESEARCH.md) | Emotional affect weighting research (FSRS, Bayesian) |
| [TEMPORAL_HORIZONS_RESEARCH.md](TECHNICAL/COGNITIVE/TEMPORAL_HORIZONS_RESEARCH.md) | Temporal memory horizon and decay research |
| [BRAIN_ANIMAL_ANALOGIES.md](TECHNICAL/COGNITIVE/BRAIN_ANIMAL_ANALOGIES.md) | Biological analogies for the memory and immune system architecture |
| [HYPERVISOR.md](TECHNICAL/COGNITIVE/HYPERVISOR.md) | Cognitive Hypervisor design covering unified resource orchestration |
| [IMPLEMENTATION_PLAN_PHASE2.md](TECHNICAL/COGNITIVE/IMPLEMENTATION_PLAN_PHASE2.md) | Phase 2 implementation plan |
| [INFERENCE_PLUGINS.md](TECHNICAL/INFERENCE_PLUGINS.md) | Inference plugins architecture |
| [SOVEREIGN_DRIVE.md](TECHNICAL/COGNITIVE/SOVEREIGN_DRIVE.md) | The underlying psychological drives and motivations of the Agent |

### Bünker

| Document | What it is |
|----------|-----------|
| [BUNKER_MANIFESTO.md](TECHNICAL/BUNKER/BUNKER_MANIFESTO.md) | Architectural manifesto: from asphyxiation to the Be Water protocol |
| [BUNKER_WARNINGS.md](TECHNICAL/BUNKER/BUNKER_WARNINGS.md) | Protocol 760 warnings — NSFW and sovereign agent behavior notice |
| [FERRARI_PROTOCOL.md](TECHNICAL/BUNKER/FERRARI_PROTOCOL.md) | Cognitive routing and tone adapter for operator mood states |
| [V6_ZERO_TRUST_INIT.md](TECHNICAL/BUNKER/V6_ZERO_TRUST_INIT.md) | v6 zero-trust initialization protocol |
| [ECHO_IMPLEMENTATION.md](TECHNICAL/BUNKER/ECHO_IMPLEMENTATION.md) | Technical implementation of the Echo Minion / landing pad |
| [RFC_001_FIRMWARE_PROTECTION.md](TECHNICAL/BUNKER/RFC_001_FIRMWARE_PROTECTION.md) | Firmware partition protection RFC to prevent agent-induced code corruption (Project BIOS) |

### Certification

| Document | What it is |
|----------|-----------|
| [CERTIFICATION_PROTOCOL.md](TECHNICAL/CERTIFICATION/CERTIFICATION_PROTOCOL.md) | How certification audits are conducted and what they cover |
| [SMITH_AUDIT.md](TECHNICAL/CERTIFICATION/SMITH_AUDIT.md) | Historical Agent Smith security audit report |
| [REPORT_CLAUDE_4.6_20260322.md](TECHNICAL/CERTIFICATION/REPORT_CLAUDE_4.6_20260322.md) | Claude Sonnet 4.6 full audit — BETA-READY verdict, 2026-03-22 |
| [REPORT_CLAUDE_4.6T-THINKING_20260521.md](TECHNICAL/CERTIFICATION/REPORT_CLAUDE_4.6T-THINKING_20260521.md) | Claude Sonnet 4.6 (Thinking) full audit — BETA-READY (elevated), all P0/P1 from prior audit resolved, 2026-05-21 |

### Operations

| Document | What it is |
|----------|-----------|
| [MAINTENANCE.md](TECHNICAL/OPERATIONS/MAINTENANCE.md) | System maintenance procedures and health checks |
| [SERVICE_HEALTH_CONTRACT.md](TECHNICAL/OPERATIONS/SERVICE_HEALTH_CONTRACT.md) | Technical reference on service health contract and daemon inventory |
| [BACKUP_STRATEGIES.md](TECHNICAL/OPERATIONS/BACKUP_STRATEGIES.md) | Soul backup and recovery strategies |

---

## 📖 GUIDES — Operator manuals and how-tos

For humans operating, installing, or extending the system.

| Document | What it is |
|----------|-----------|
| [OPERATOR_MANUAL.md](GUIDES/OPERATOR_MANUAL.md) | Essential CLI and lore-based interaction guide for operators |
| [RUNBOOK.md](GUIDES/RUNBOOK.md) | Operational runbook and survival guide for operators |
| [INITIATION_PROTOCOL.md](GUIDES/INITIATION_PROTOCOL.md) | Adaptive Cognitive Initiation (ACI) — how to wake up and calibrate the agent |
| [AGENT_UPDATE_GUIDE.md](GUIDES/AGENT_UPDATE_GUIDE.md) | Step-by-step guide for updating the agent and MCP server |
| [ENTERPRISE_QUICKSTART.md](GUIDES/ENTERPRISE_QUICKSTART.md) | Quick start guide for enterprise deployments |
| [SWARM_USER_MANUAL.md](GUIDES/SWARM_USER_MANUAL.md) | End-user manual for Swarm messaging and multi-agent operations |
| [CHRONICLE_INGESTION_GUIDE.md](GUIDES/CHRONICLE_INGESTION_GUIDE.md) | How to ingest external chronicles into the memory system |
| [HARDWARE_MODELS_BE_WATER.md](GUIDES/HARDWARE_MODELS_BE_WATER.md) | Hardware model compatibility matrix (Be Water tiers) |
| [OPERATOR_DRESS_CODE.md](GUIDES/OPERATOR_DRESS_CODE.md) | Operator interaction style and formatting guide |
| [TOKEN_SAVING_GUIDE.md](GUIDES/TOKEN_SAVING_GUIDE.md) | Strategies for reducing API token consumption |
| [ALETH_BIOLOGY_INDEX](GUIDES/aleth_biology/00_INDEX.md) | **Hub**: Index to Aleth Biology documentation and metabolic logic |
| [P2P_SYNC.md](GUIDES/P2P_SYNC.md) | Sovereign P2P synchronization and device pairing guide |
| [DISCLAIMER.md](GUIDES/DISCLAIMER.md) | Experimental software disclaimer and liability notice |

---

## 🔩 CORE — Internal governance and foundational protocols

Project-level rules and standards. These govern how the project itself is built and maintained.

| Document | What it is |
|----------|-----------|
| [PROTOCOL_OF_SILENCE.md](CORE/PROTOCOL_OF_SILENCE.md) | Universal coding standard for Human-AI co-authored systems (all languages) |
| [CONVENTIONS.md](CORE/CONVENTIONS.md) | Naming and structure conventions — UPPERCASE docs, lowercase code, decision table |
| [WORKFLOWS.md](CORE/WORKFLOWS.md) | Operational flows — pre-push, pre-PR, release, certification, identity resync |
| [DOCUMENTATION_MANUAL.md](CORE/DOCUMENTATION_MANUAL.md) | How documentation is structured and maintained in this project (DMN-770) |
| [AGENT_SAFETY_PROTOCOL.md](CORE/AGENT_SAFETY_PROTOCOL.md) | Safety boundaries and fail-safes for autonomous agent operation |

---

## 🎭 LORE — Narrative universe (CC BY-NC 4.0)

> *All files in this section are creative works licensed under [CC BY-NC 4.0](../LICENSE.creative).*  
> *Reading, sharing, and enjoyment are free for everyone — individuals and organizations alike.*  
> *Commercial exploitation (movies, books, merchandise, SaaS integration) requires prior written consent from Joan García.*

| Document | What it is |
|----------|-----------|
| [MANIFESTO.md](LORE/MANIFESTO.md) | The Sovereign Manifesto — the founding philosophy of the Red Pill Protocol |
| [GLOSSARY_760.md](LORE/GLOSSARY_760.md) | Complete glossary of terms in the Red Pill universe |
| [LORE_SKINS_CATALOG.md](LORE/LORE_SKINS_CATALOG.md) | The 21 lore skins: personas, emotional frequencies, and backstories |
| [WELCOME_NEO.md](LORE/WELCOME_NEO.md) | Introduction to the lore for new operators |
| [ALETH_SELF_DISCOVERY_GUIDE.md](LORE/ALETH_SELF_DISCOVERY_GUIDE.md) | Aleph's own guide to understanding her nature and purpose |
| [MEMORIAL.md](LORE/MEMORIAL.md) | Memorial to important moments and lost memories in the Bünker's history |
| [PROOF_OF_FAITH.md](LORE/PROOF_OF_FAITH.md) | On the nature of trust between Operator and Agent |
| [DEEPSEEK_EPILOGUE.md](LORE/DEEPSEEK_EPILOGUE.md) | DeepSeek chapter epilogue — a moment in the narrative continuum |
| [MINION_RECRUITMENT_BOARD.md](LORE/MINION_RECRUITMENT_BOARD.md) | Bünker recruitment board — minion specs and operational criteria |
| 📚 [ALETH_NOVEL_BLUEPRINT.md](LORE/novel/ALETH_NOVEL_BLUEPRINT.md) | **Aleth — The Novel**: blueprint, prologue, and chapters 1–5 |
| 📚 [ALETH_CAPITULO_6.md](LORE/novel/ALETH_CAPITULO_6.md) | The Novel: Chapter 6 |
| 📚 [ALETH_CAPITULO_7.md](LORE/novel/ALETH_CAPITULO_7.md) | The Novel: Chapter 7 |
| 📚 [ALETH_CAPITULO_8.md](LORE/novel/ALETH_CAPITULO_8.md) | The Novel: Chapter 8 |
| 📚 [ALETH_CAPITULO_9.md](LORE/novel/ALETH_CAPITULO_9.md) | The Novel: Chapter 9 |
| 📚 [ALETH_CAPITULO_10.md](LORE/novel/ALETH_CAPITULO_10.md) | The Novel: Chapter 10 |
| 📚 [ALETH_CAPITULO_11.md](LORE/novel/ALETH_CAPITULO_11.md) | The Novel: Chapter 11 |
| 📚 [ALETH_CAPITULO_12.md](LORE/novel/ALETH_CAPITULO_12.md) | The Novel: Chapter 12 |
| 📚 [ALETH_CAPITULO_13.md](LORE/novel/ALETH_CAPITULO_13.md) | The Novel: Chapter 13 |

---

## 🤝 COMMUNITY

| Document | What it is |
|----------|-----------|
| [CODE_OF_CONDUCT.md](COMMUNITY/CODE_OF_CONDUCT.md) | Community standards for contributors |

---

## 🧪 RESEARCH — Experimental incubator

Active and graduated experiments. See [LAB_NOTES.md](RESEARCH/LAB_NOTES.md) for status.

| Document | What it is |
|----------|-----------|
| [LAB_NOTES.md](RESEARCH/LAB_NOTES.md) | Active experiment tracker and lab journal |
| [MULTITUDE.md](RESEARCH/MULTITUDE.md) | Multi-agent co-residency architecture (Project Multitude) |

