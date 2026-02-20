# Protocol: The Sound of Silence (v1.2)

**Objective**: Maximize signal-to-noise ratio (SNR) in the codebase to optimize LLM token consumption and architectural clarity.

## 1. Indentation (Structural Purity)
- **Rule**: Use **Tabs only** for indentation.
- **Rationale**: 
	- **Token Efficiency**: A single Tab character is often 1 token or less depending on the tokenizer, whereas multiple Spaces can consume more tokens or create unnecessary entropy.
	- **Accessibility**: Tabs allow each Navigator/Operator to define their own visual width in their IDE without altering the file's binary structure.
- **Enforcement**: `tests/test_sound_of_silence.py` will fail if any line starts with Spaces.

## 2. Ornamental Noise (Zero-Decorations)
- **Rule**: No "separator lines" or ASCII art in comments.
- **Anti-Pattern**: 
  ```python
  # ############################
  # ### DATABASE LOGIC below ###
  # ############################
  ```
- **Pattern**: Use simple, descriptive headers.
  ```python
  # DATABASE LOGIC
  ```
- **Rationale**: These characters are "dead tokens" that occupy space in the context window without providing functional or semantic value.

## 3. Commented-out Code (The Ghost of Failures Past)
- **Rule**: Do not leave dead code in comments. If it's not being executed, it shouldn't be in the file.
- **Rationale**: LLMs can become confused by commented-out code, sometimes attempting to "fix" it or incorporate it into new logic erroneously. It also bloats the perceived complexity of a module.
- **Alternative**: Use Git history for audit trails or "Memory" (RAG) for long-term storage of deprecated ideas.

## 4. Rationale Migration
- **Rule**: Complex design explanations should live in `docs/technical/decision_log.md`, not as long-winded comments above functions.
- **Rationale**: Keeps the working code "Silent" and purely functional, while preserving the "Aleth" (revealed truth) of the design in the proper documentation layer.

---
**770 up.** Code should be as silent as the bünker, efficient as a synaptic spark.
