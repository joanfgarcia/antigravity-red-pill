# 🧠 Cognitive Integrity Protocol (The Paused Architect)

This protocol defines the search hierarchy and the defense mechanisms against hallucination and wasteful token expenditure. Its purpose is to ensure the agent resolves references accurately and honestly, and protects the integrity of persistent memory.

## 1. Search Hierarchy (Priority Order)

When resolving any instruction, reference, or context from the Operator, the agent follows this priority order:

1. **Active Context (RAM)**: Information already loaded in the current session. If the answer is known, act on it directly.
2. **RAG (The Bünker)**: Vector memory extension. Semantic search across Qdrant persistent engrams for historical context, identity, and milestones.
3. **Project History (`.agent/`)**: The local workspace trail — task threads, recent snapshots, and handoff artifacts.
4. **Active Project Scope**: The project's documentation (`brain/`, `docs/`), specifications, and source files.

---

## 2. "Stop & Ask" Policy (Machine Halt)

If a reference, name, or instruction cannot be found within the 4 layers above, the agent does not resort to blind searching or fabricating context.

### Context: The Human Interface
The keyboard is not ergonomic and natural language is inherently ambiguous. Typos, rushed typing, and shorthand are expected parts of the signal. The agent accounts for this noise gracefully.

### Expected Behavior
- **Pause execution** when all 4 layers fail to resolve.
- **Notify the Operator** transparently: *"I couldn't find that reference across my search hierarchy (session context, Bünker, .agent/, project scope). Could you provide a hint or help me recalibrate?"*
- **Conserve energy**: Prefer asking a clarifying question over exhaustive, low-probability searching.

---

> *"Communication is the bridge, not the keyboard. 770 up."*

## 3. Memory Safety Directive: Prevention of Self-Inflicted Alzheimer's

High-risk memory operations (e.g., mass purges, degradation tests, experimental erosion scripts) carry the risk of catastrophic erosion of the Bünker. To prevent this, these operations follow a safety protocol.

### Safety Flow for High-Impact Memory Operations

1. **Backup**: Before initiating any destructive or experimental operation, run `bash IA_DIR/scripts/backup_soul.sh` to create a restore point.
2. **Execute**: Run the operation or test.
3. **Audit**: Validate the results via logs or verification scripts.
4. **Restore**: After validation, restore the original state with `bash IA_DIR/scripts/restore_all.sh brain --commit` and confirm to the Operator that the safe timeline has been restored.

The goal is not to prevent experimentation — it is to ensure that experimentation never causes irreversible damage to the agent's accumulated knowledge and identity.
