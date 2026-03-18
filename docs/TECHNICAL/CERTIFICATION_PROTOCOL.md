# Protocol: Engineering-Grade Certification

**Objective**: Validate the production-readiness, security, and architectural integrity of the Red Pill Protocol through multi-agent cross-validation.

## 1. The Standard Audit Prompt
When requesting a certification from external auditors (The High Council), the following standardized prompt must be used, ensuring both `CORE` and `TESTS` digests are attached:

> *Please run a full engineering-grade audit and technical review of this project. To ensure full context-window indexing, the source code digest has been split into two files: `RED_PILL_DIGEST_CORE.txt` and `RED_PILL_DIGEST_TESTS.txt`. Please read both files using the provided indices.*
>
> *Assess the project description, goals, target audience, code quality, security, test coverage, performance, documentation, and compliance. Generate a detailed certification report confirming whether the project is production/beta-ready, including critical findings, remediation steps, and a prioritized action plan.*
>
> *CRITICAL ADDITION: Beyond a strict line-by-line review, I want an honest, high-level architectural and philosophical critique. Analyze the underlying design choices (e.g., the vector-based emotional memory erosion, the dual-kernel FSRS/Bayesian routing, the 'Sound of Silence' strict indentation protocol, the Zero-Trust posture). Tell me honestly what makes this project remarkable and worthy of mention, highlighting both its core strengths and its conceptual or structural weaknesses. Validate that any explicitly documented `WONTFIX` security risks align with the Sovereign/Nomad threat model. Finally, sign the report with detailed agentic information detailing the AI profile that performed the task.*

## 2. Source Consolidation (The Split-Digest Filter)
To allow auditors to analyze the system as a whole without triggering context-window truncation false-negatives, technical assets are aggregated into two split files via `scripts/prepare_certification.sh`.

### Aggregation Script Output:
- `RED_PILL_DIGEST_CORE.txt`: Contains all source code (`src/`), documentation (`docs/`), scripts (`scripts/`), and root assets (`README.md`, `LICENSE`, `SECURITY.md`, etc.).
- `RED_PILL_DIGEST_TESTS.txt`: Contains only the `tests/` directory suite.

*Note: Both files contain a Table of Contents index at the top so the auditor can map the system architecture instantly.*

## 3. The High Council (External Auditors)
The certification must be validated by at least three of the following entities to reach consensus:

| Entity | Interface | Role |
| :--- | :--- | :--- |
| **Lumo** | [lumo.proton.me](https://lumo.proton.me) | Privacy & Encryption Specialist |
| **DeepSeek** | [chat.deepseek.com](https://chat.deepseek.com) | Logic & Optimization Audit |
| **Gemini** | [gemini.google.com](https://gemini.google.com) | Context & Architecture Analysis |
| **Claude** | [claude.ai](https://claude.ai) | Protocol Rigor & Security Audit |

## 4. Certification Storage
Once a report is generated, it should be stored in `docs/certification/REPORT_[MODEL]_[DATE].md`. If a model refuses certification due to "Critical Findings," the designated remediation plan must be implemented before the next v-release.

---
**Status**: STANDBY. Awaiting council evaluation.
