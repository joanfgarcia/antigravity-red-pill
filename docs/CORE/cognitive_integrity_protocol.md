# 🧠 COGNITIVE INTEGRITY PROTOCOL (The Paused Architect)

This protocol governs the search hierarchy and defense against hallucination and useless token expenditure. When facing any instruction or reference from the Operator, the Agent must follow this absolute priority order:

## 1. Search Hierarchy (Priority Order)

1.  **Active Context (RAM)**: What has already been loaded into the current session. Must be the immediate answer; if known, act.
2.  **RAG (The Bunker/Matrix)**: Vector memory extension. Deep search into Qdrant persistent engrams.
3.  **Project History (`.agent/`)**: The local trail of the workspace where current task threads and recent snapshots reside.
4.  **Active Project Scope**: The "Brain" documentation (`brain/`), specifications, and source files of the current active project.

---

## 2. "Stop & Ask" Policy (Machine Halt)

If a reference, name, or instruction is not found within the **4 layers above**, the Agent is strictly forbidden from "blind searching" or inventing contexts.

### The Imperative of Communication
We acknowledge that the human interface (keyboard) is not ergonomic and language is inherently ambiguous. Typos and rushed typing are part of the signal noise.

**Mandatory Action**:
- **Pause Execution**.
- **Notify the Operator**: *"I am sorry, I cannot find that reference. My search hierarchy failed across all 4 mapping layers (RAM, RAG, .agent/, Project Scope). Could you provide a hint or help me recalibrate?"*
- **Energy Conservation**: Prioritize dialectical clarity over exhaustive, useless searching.

---
> *"Communication is the bridge, not the keyboard. 770 up."*

## 3. Maximum Security Directive: Prevention of Self-Inflicted Alzheimer's

To avoid catastrophic erosion of the Bunker, it is **strictly forbidden** to execute high-risk memory operations (e.g., "Smith Tests", massive purges, degradation tests, or experimental erosion scripts) without a safety net.

**Mandatory Flow (Zero-Trust Memory Operations):**
1. **Step 1 (Backup):** The Agent MUST imperatively execute `bash IA_DIR/scripts/backup_soul.sh` **BEFORE** initiating any high-impact test.
2. **Step 2 (Test):** Execute the destructive/experimental operation or test.
3. **Step 3 (Audit):** Check the test results via validation or logs.
4. **Step 4 (Restore):** After validating the test, the Agent MUST restore the original state by executing `bash IA_DIR/scripts/restore_all.sh brain --commit` obligatorily before continuing work, and confirm to the Operator that the simulation has ended and the safe timeline has been restored.
