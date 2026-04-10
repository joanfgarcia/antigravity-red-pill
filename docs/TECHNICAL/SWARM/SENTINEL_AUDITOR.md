# Sentinel Auditor: Epidemiological Surveillance Protocol

**Status**: Operational (v6.5.2)  
**Alliance**: Project MULTITUDE (Node #1)  
**Codename**: "The Medical Examiner"

## 1. Overview
The Sentinel Auditor is a background diagnostic minion designed to monitor the long-term vitality of the Red Pill ecosystem. Unlike the immediate "nociceptive" response of the Neuro-Immune system (which detects a single failure and attempts to heal it), the Auditor analyzes the **frequency and patterns** of failure over time.

## 2. Core Capabilities

### 2.1 Mean Time Between Failures (MTBF)
The Auditor calculates the temporal distance between entries in the `signal_memories` collection. 
- **Healthy**: MTBF > 168 hours (1 week).
- **Stressed**: MTBF < 24 hours.
- **Critical**: MTBF < 1 hour.

### 2.2 Lazarus Loop Detection
Detects chronic failure-and-recovery cycles. If a specific "tissue" (e.g., CUDA or Qdrant) is healed by the `Healer` but fails again within a short window, the Auditor flags it as a **Lazarus Loop**. This indicates that the root cause is persistent and requires human intervention or a more aggressive architectural fix.

### 2.3 Vitality Reporting
Generates a structured Markdown report containing:
- **System Vitality Index (SVI)**: A weighted score (0–100) based on signal density and severity.
- **Cortex Hypoxia Check**: Verification of Qdrant responsiveness and memory flow.
- **Hardware Telemetry**: Aggregated CPU/GPU stats over the audit window.

## 3. Deployment & Execution
The Auditor is decoupled from the main MCP loop. It can be triggered in three ways:
1. **Manual Trigger**: Via the `run_sentinel_audit` MCP tool.
2. **Autonomous Pulse**: Integrated into the `redpill-wake.timer` ritual.
3. **Emergency Trigger**: Automatically invoked if the System Vitality Index drops below a critical threshold (30%).

## 4. Reporting Pipeline
Reports are not injected into the conversation directly (to avoid noise). They are delivered to the **MinionInbox** (`minion_inbox.db`):
1. Auditor writes Markdown blob to SQLite.
2. The `check_minion_inbox` tool reveals unread reports.
3. The Operator decides when to review the findings.

## 5. Security & Sovereignty
- **Filtered Analysis**: The Auditor only reads `signal_memories`. It does not have access to `social_memories` or `story_memories`.
- **Zero-Daemon**: Operates as a oneshot process via the project's `.venv` using the `GET_PYTHON()` helper.
