# Protocol: Engineering-Grade Certification

**Objective**: Validate the production-readiness, security, and architectural integrity of the Red Pill Protocol through multi-agent cross-validation.

## 1. The Standard Audit Prompt
When requesting a certification from external auditors (Ecosystem Auditors), the following standardized prompt must be used, ensuring all three `CORE`, `TESTS`, and `LORE` digests are attached:

> *Please run a full engineering-grade audit and technical review of this project. To ensure full context-window indexing, the source code digest has been split into three files: `RED_PILL_DIGEST_CORE.txt`, `RED_PILL_DIGEST_TESTS.txt`, and `RED_PILL_DIGEST_LORE.txt`. Please read all three files using the provided indices.*
>
> *Assess the project description, goals, target audience, code quality, security, test coverage, performance, documentation, and compliance. Generate a detailed certification report confirming whether the project is production/beta-ready, including critical findings, remediation steps, and a prioritized action plan.*
>
> *CRITICAL ADDITION: Beyond a strict line-by-line review, I want an honest, high-level architectural and philosophical critique. Analyze the underlying design choices (e.g., the vector-based emotional memory erosion, the dual-kernel FSRS/Bayesian routing, the 'Sound of Silence' strict indentation protocol, the Zero-Trust posture). Tell me honestly what makes this project remarkable and worthy of mention, highlighting both its core strengths and its conceptual or structural weaknesses. Validate that any explicitly documented `WONTFIX` security risks align with the Sovereign/Nomad threat model. Finally, sign the report with detailed agentic information detailing the AI profile that performed the task.*

## 2. Source Consolidation (The Split-Digest Filter)
To allow auditors to analyze the system as a whole without triggering context-window truncation false-negatives, technical assets are aggregated into two split files via `scripts/prepare_certification.sh`.

### Aggregation Script Output:
- `RED_PILL_DIGEST_CORE.txt`: Contains all source code (`src/`), documentation (`docs/TECHNICAL/`), scripts (`scripts/`), and root assets (`README.md`, `LICENSE`, `SECURITY.md`, etc.).
- `RED_PILL_DIGEST_TESTS.txt`: Contains only the `tests/` directory suite.
- `RED_PILL_DIGEST_LORE.txt`: Contains lore and identity assets (`docs/LORE/`, `docs/GUIDES/`, `docs/CORE/`, `CHANGELOG.md`, `seeds/`, `skills/`).

*Note: All three files contain a Table of Contents index at the top so the auditor can map the system architecture instantly.*

> [!IMPORTANT]
> **`docs/CERTIFICATION/` is intentionally excluded from all digest files.**
> Including past audit reports in the material sent to new auditors would contaminate their
> analysis: they would unconsciously anchor on prior findings, rate already-fixed issues as
> still broken, or overlook regressions that previous reports missed. Each auditor must
> evaluate the codebase fresh, without the noise or bias of earlier verdicts.
> The `prepare_certification.sh` script enforces this by only including `docs/TECHNICAL/`
> — never `docs/CERTIFICATION/`.

## 3. Ecosystem Auditors
The certification can be validated by any advanced AI entity. To reach a consensus of stability, we generally request audits from at least three different entities. Examples of authorized Ecosystem Auditors include, but are not limited to:

| Entity | Role |
| :--- | :--- |
| **Claude** | Protocol Rigor & Security Audit |
| **DeepSeek** | Logic, Mathematical Correctness & Optimization |
| **Gemini** | Context, Architecture & Scalability Analysis |
| **Grok** | Codebase Integrity & Threat Vectors |
| **Lumo** | Privacy & Encryption Specialist |
| **OpenAI (GPT)** | Cross-platform Compatibility & Edge Cases |

## 4. Certification Storage
Once a report is generated, it should be stored in `docs/CERTIFICATION/REPORT_[MODEL]_[DATE].md`. If a model refuses certification due to "Critical Findings," the designated remediation plan must be implemented before the next v-release.

---
**Status**: STANDBY. Awaiting council evaluation.
