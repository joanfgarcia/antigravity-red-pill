# Protocol: Engineering-Grade Certification

**Objective**: Validate the production-readiness, security, and architectural integrity of the Red Pill Protocol through multi-agent cross-validation.

## 1. The Audit Prompt
When requesting a certification from external auditors (The High Council), the following standardized prompt must be used:

> *Please run a full engineering-grade audit and technical review -- including project description, goals, target, audience, code-quality, security, test coverage, performance, documentation, and compliance checks -- and generate a detailed certification/report that confirms whether the project is production ready. Include any critical findings, recommended remediation steps, and prioritized action plan. Also sign the report with detailed agentic information that performed the task.*

## 2. Source Consolidation (The "Single Engram" Filter)
To allow auditors to analyze the system as a whole, all technical assets must be aggregated into a single file named `proyecto_completo.txt`.

### Aggregation Script (`scripts/prepare_certification.sh`):
```bash
# Use git ls-files to respect .gitignore and only include tracked + untracked/non-ignored files.
git ls-files --cached --others --exclude-standard | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico)$' | while read f; do
	if [ "$f" != "proyecto_completo.txt" ] && [ -f "$f" ]; then
		echo -e "\n\n===== FILE: $f =====\n"
		cat "$f"
	fi
done > proyecto_completo.txt
```

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
