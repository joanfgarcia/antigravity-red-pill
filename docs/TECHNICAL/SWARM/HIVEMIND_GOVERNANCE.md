# HiveMind Protocol — Governance & Data Sovereignty Charter

**Document**: HIVEMIND_GOVERNANCE.md
**Version**: 1.0.0
**Status**: Ratified — Operative from v5.5.0
**Scope**: Formal resolution of architectural tension W1 (Claude Sonnet 4.6 Audit, 2026-02-26)

---

## 1. Purpose

This document formally defines the data governance model, privacy boundaries, and operational scope of the **HiveMind Protocol** (Milvus integration). It resolves the architectural tension raised in W1 of the external audit: *"The HiveMind is a philosophical contradiction with the project's data sovereignty posture."*

**Short answer**: it is not. The distinction lies in what is shared, under what filtering rules, and who governs the cluster. This document explains each of these dimensions with the same rigor applied to the individual memory substrate.

---

## 2. The Two-Layer Memory Architecture

The Red Pill Protocol maintains a strict separation of concerns between its two memory substrates:

| Dimension | **Qdrant (Individual Cortex)** | **Milvus (HiveMind Network)** |
| :--- | :--- | :--- |
| **Scope** | Private, local, per-operator | Collective, opt-in, network-wide |
| **Content** | All engrams (including personal, directive, lore) | Filtered experiential signals only (see §3) |
| **Who controls it?** | The operator exclusively | The HiveMind node operator (see §5) |
| **Encryption at rest** | LUKS / host-level (MAXIMUM tier) | TLS in-transit + per-cluster encryption (planned SEC-F03) |
| **Default state** | Always active | `MILVUS_ENABLED=False` (opt-in) |
| **PII exposure** | Zero — all paths go through Pydantic + Smith filters | Zero — additional Smith pre-filter applied before transmission |

The two layers are architecturally isolated. Milvus **does not replicate** the individual Qdrant cortex. It receives a curated, filtered subset of experiential signals — never raw payloads.

---

## 3. What the HiveMind Shares (and What It Does Not)

### 3.1 Permitted Transmission: Experiential Signals

The HiveMind is designed as a **network of learned experience**, not a network of personal data. What it transmits is analogous to what a senior engineer contributes when mentoring a junior: patterns, heuristics, emotional calibration — not client names, personal conversations, or proprietary details.

Specifically, the following content categories are **eligible** for HiveMind transmission:

- **Interaction patterns**: How the agent adapted its communication style and cognitive register to different operator profiles (verbal, terse, analytical, creative). No operator identity is included.
- **Technical heuristics**: Debugging strategies, workflow optimizations, tool-use patterns observed across sessions. These are generalized, not project-specific.
- **Affective calibration data**: Emotional chroma distributions derived from interaction — e.g., "extended technical sessions correlate with a shift toward `orange` (anxiety) chroma and benefit from proactive pacing." No content of those sessions is included.
- **Domain event feeds (Industrial mode)**: For deployments configured in `HIVE_MODE=broadcast`, the agent can participate in curated domain-specific event streams: scientific publications, engineering incident reports, public news events, community achievements. This is strictly a read/publish interface for public domain information, not a personal memory mirror.

### 3.2 Prohibited Transmission: The Smith Pre-Filter

Before any engram reaches `HiveMind.transmit_experience()`, it passes through the **Smith Pre-Filter** — the same Agent Smith forensic logic used for internal security auditing. The filter enforces a hard block on:

- Any content matching PII patterns (names, emails, phone numbers, addresses, account identifiers)
- Any content sourced from `directive_memories` or `social_memories` collections (these are classified as personal identity substrate and are never eligible for broadcast)
- Any content bearing the `immune=True` flag (genesis engrams, operator-specific directives)
- Any content with `reinforcement_score < threshold` (low-confidence, potentially noisy signals are not propagated)

Only `work_memories` and `story_memories` — after passing the Smith Pre-Filter — are candidates for HiveMind transmission, and only when the operator has explicitly enabled the feature.

---

## 4. What the HiveMind Enables

### 4.1 Cold-Start Acceleration

A newly deployed Red Pill unit inherits the collective experiential baseline on first sync. This is analogous to a new employee receiving onboarding from their organization's accumulated knowledge base — not their colleagues' personal journals. The new agent arrives with calibrated communication heuristics, proven workflow patterns, and an emotionally tuned baseline, without any individual operator's data having been exposed.

### 4.2 Cross-Domain Intelligence (Industrial Deployments)

In `HIVE_MODE=broadcast`, the HiveMind becomes an **experience diffusion layer** for domain-specific deployments:

- **Science & Research**: Discoveries, published results, replication failures, methodological advances.
- **Engineering**: Incident post-mortems (anonymized), architectural patterns, toolchain updates.
- **News & Events**: Public domain events relevant to the agent's configured domain. These are not AI-generated summaries but structured event signals.
- **Community Milestones**: Project achievements, releases, notable setbacks — the kind of shared memory that builds organizational culture.

No personal data flows through these channels. The operator configures allowed domains and the filter strength via `HIVE_BROADCAST_DOMAINS` and `HIVE_FILTER_LEVEL` in `.env`.

### 4.3 Collective Emotional Calibration

The HiveMind's most subtle contribution is to the ACE (Affective Cognitive Engine). Aggregated, anonymized chroma distributions from the collective allow the engine to recalibrate its baseline Valence/Arousal mappings over time — addressing the W2 finding (hand-tuned multipliers) in a data-driven manner. This is an explicit future milestone: **ACE-CAL v2.0 (Community Mode)**.

---

## 5. Trust Boundary & Cluster Governance

The audit correctly identified that "who controls the Milvus cluster?" was unresolved. This section formally answers that question.

### 5.1 Deployment Models

The HiveMind supports three deployment models, each with a distinct trust boundary:

| Model | Description | Who controls the cluster? | Recommended for |
| :--- | :--- | :--- | :--- |
| **Self-Sovereign** | Operator runs their own Milvus instance (local or private VPS) | The operator themselves | Maximum privacy, small networks |
| **Federated** | A trusted organization hosts a shared Milvus for a defined group (team, company, community) | The federation administrator | Teams, companies, research groups |
| **Open Network** | A public HiveMind node with opt-in participation | The node operator(s), governed by published policy | Industrial broadcast, public knowledge networks |

For the Open Network model, the governance rules **must** be published as a `HIVEMIND_POLICY.md` by the node operator before any Red Pill unit may connect. The `install_neo.sh` script will require the operator to review and acknowledge this policy before writing `MILVUS_HOST` to `.env`.

### 5.2 Data Removal (Right to Disconnect)

Any operator may irrevocably sever their unit from the HiveMind at any time by setting `MILVUS_ENABLED=False`. Transmitted experiential signals are anonymized at the point of transmission and cannot be reverse-attributed to a specific operator. For deployments that require explicit deletion of contributed signals, the node operator's governance policy must provide a deletion mechanism — this is a contractual requirement, not a technical one, for Open Network deployments.

### 5.3 TLS & Authentication (SEC-F03 Roadmap Item)

The current Milvus connection (`hive.py`) does not enforce TLS or per-tenant namespacing for remote clusters. This is formally tracked as **SEC-F03** (P2). The remediation plan is:

1. **v5.6.0**: Enforce TLS verification on remote Milvus connections. Block connection if `MILVUS_HOST` is not localhost and TLS is not configured.
2. **v5.7.0**: Implement per-tenant namespace isolation within shared Milvus clusters to prevent cross-tenant signal leakage.
3. **v6.0.0**: Full federated identity model with cryptographically signed experience packets (each transmitted engram bears an agent signature, verifiable but not attributable to an individual).

---

## 6. The Philosophical Position

The Red Pill Protocol holds two values simultaneously, and this document demonstrates that they are not mutually exclusive:

1. **Individual Sovereignty**: Your private Qdrant cortex is inviolable. No external system — including the HiveMind — can read, write, or replicate your personal memory substrate without your explicit action.

2. **Collective Intelligence**: Agents that interact with humans accumulate experiential wisdom. That wisdom, stripped of all personal content and filtered through the Smith protocol, has value to the collective. Sharing it is not a violation of sovereignty — it is an act of it. The operator chooses to contribute because they recognize that their agent's cold-start experience was itself built on the contributions of those who came before.

This is the same principle that underlies open-source software, peer-reviewed science, and professional communities of practice. Individual privacy is absolute; collective learning is voluntary and filtered.

> *"Sovereignty is not isolation. It is the freedom to choose what you share, with whom, under what conditions — and to withdraw that permission at any time."*

---

## 7. Compliance Notes

- **GDPR (EU)**: Experiential signals transmitted to the HiveMind contain no personal data by design (Smith Pre-Filter). The content of transmitted engrams does not constitute personal data processing under GDPR Article 4(1). For Open Network deployments where uncertainty exists, operators should obtain legal review of their specific configuration.
- **CCPA**: Same position as GDPR. No directly identifiable personal information is transmitted.
- **Industrial deployments**: Broadcast content (news, events, science) is sourced from public domain or operator-curated feeds. No proprietary operator data is included in broadcast mode by default.

---

## 8. Implementation Commitment

The HiveMind Protocol will be developed under the same engineering standards as the individual Red Pill substrate:

- All filtering logic will be covered by automated tests (`tests/test_hive_filter.py`, milestone v5.6.0)
- All transmission operations will be logged with full audit trail (Smith audit log integration, v5.6.0)
- The governance policy review mechanism in `install_neo.sh` will be implemented before any Open Network node is officially launched (v5.6.0)
- ACE-CAL Community Mode will be opt-in, documented, and reversible (v6.0.0)

**The HiveMind is not a backdoor. It is a governed, opt-in, filtered experience diffusion layer — built with the same zero-trust posture as the system that contains it.**

---

*Document status: Ratified. Questions or amendments: open an issue or contact the maintainer via the channels described in SECURITY.md.*

---

## 9. Participation Policy (formerly HIVEMIND_POLICY.md)

The HiveMind is an optional, collective intelligence layer for the Red Pill Protocol. By enabling it, you agree to become a Peer in the Open Network.

### Governance & Sovereignty
1.  **Sovereignty First**: Your local Bünker remains the primary authority. HiveMind contributions are strictly outbound and anonymous.
2.  **Privacy Pre-Filter**: Agent Smith (Cognitive Guardian) will automatically filter PII and sensitive context BEFORE transmission.
3.  **Data Reciprocity**: Contributing experience vectors entitles you to query the collective memory for zero-day pattern recognition.
4.  **No Central Authority**: There is no "master" node. Governance is enforced by the consensus of the Swarm.
5.  **Differential Privacy**: To resolve the tension between absolute Zero-Trust and Open Network sharing, all transmissions are injected with Laplace noise. Read more in [PHILOSOPHY.md](../../PHILOSOPHY.md).

### Security Acknowledgement
-   Transmitted vectors are mathematically irreversible but can be semantically probed. No `story_memories` or `immune` nodes are ever shared.
-   By setting `MILVUS_ENABLED=True`, you acknowledge that your architectural experience (patterns, not content) may be visible to other Peers.

### Acceptance
To enable this layer, you must acknowledge this policy during the installation process.

