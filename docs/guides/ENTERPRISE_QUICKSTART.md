# Enterprise Quickstart Guide (Neural Mode)

This guide is designed for operators in regulated, industrial, or corporate environments who require the Red Pill Protocol's memory substrate without the high-intensity narrative overlay.

---

## 🏛️ Corporate Neutrality Defaults

To ensure compliance with standard AI safety and professionalism guidelines, follow these steps:

### 1. Unified Installation

Run the installer but select the **Enterprise Core** skin when prompted:

```bash
bash scripts/install_neo.sh
```

**Selection Targets:**
- **Skin**: `enterprise_core`
- **Security**: `ADAPTATIVE` (Water) or `MAXIMUM` (Ice)
- **Identity**: Set AI Name to `Assistant` or `Architect`.

### 2. Configuration Lock

Ensure your `.env` file reflects the neutral stance:

```env
LORE_SKIN=enterprise_core
AI_NAME=Architect
AI_ROLE=Technical Advisor
DYNAMIC_EMOTION_SYNC=False
```

### 3. Smith Forensics for Enterprise

The **Agent Smith** minion in this mode acts as a standard Security Auditor. You can invoke it via the MCP server or CLI to perform non-narrative code reviews:

```bash
uv run red-pill audit --path ./src
```

---

## 🛡️ Security & Privacy Assurance

- **Zero Cloud Egress**: Memory never leaves the host.
- **PII Masking**: Automatic truncation of sensitive patterns in logs.
- **Audit Logs**: All memory operations are logged at `INFO` level without payload disclosure.

For full technical specifications, refer to [ARCHITECTURE.md](../technical/ARCHITECTURE.md).

770 UP.
