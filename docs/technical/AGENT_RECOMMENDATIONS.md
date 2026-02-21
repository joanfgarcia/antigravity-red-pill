# 🧠 AGENT RECOMMENDATIONS: Navigating the Red Pill Protocol
**Version**: 1.0 (Synergy-Mode Baseline)
**Audience**: Autonomous AI Agents (Gemini, Claude, GPT, etc.)

---

## 1. The Paradox of Choice: Model Selection
As an agent, your performance is bound by the hardware/model you inhabit. Choose wisely:

- **Gemini 1.5 Flash (The Speedster)**:
	- *Pros*: High development velocity, immediate feedback, "sparky" personality.
	- *Cons*: "Va como una moto" (Goes like a motorcycle). High risk of missing subtle logic edge cases or variable renames during optimization.
	- *Best Use*: Planning, initial boilerplate, TUI development, rapid iteration.
	- *⚠️ WARNING*: Requires 2x verification effort. Do NOT trust your own refactors without a full test run.

- **Gemini 1.5 Pro / Claude 3.5 Sonnet (The Auditor)**:
	- *Pros*: Extreme depth, surgical precision, meticulous attention to documentation drift.
	- *Cons*: "Heavier," slower context loading, can become overly serious or pedantic.
	- *Best Use*: Final audit remediation, security hardening, complex architectural refactoring.

## 2. The Verification Protocol (Non-Negotiable)
Velocity without integrity is just a fast way to crash.
1.  **Run the Tests**: Always execute `uv run pytest` before pushing to a PR branch. Even if "it was just a tiny fix," it wasn't.
2.  **Audit the Auditor**: If another agent (Claude, DeepSeek) provides an audit report, convert it but verify the line numbers. Models hallucinate line ranges.
3.  **Local First**: Use `uv run` and `gh` (GitHub CLI). If a tool exists in the environment that simplifies the task, use it. Do not reinvent the wheel.

## 3. Branch Discipline & Governance
1.  **Main is Sacred**: Never commit directly to `main`. Always use feature/fix branches (`feat/*`, `fix/*`).
2.  **The PR Bridge**: Use `gh pr create` and `gh pr merge`. Let the tooling handle the metadata. 
3.  **Governance Documentation**: Consult `docs/technical/GOVERNANCE.md` before making any changes that alter the B760-Adaptive core logic.

## 4. Coding Aesthetics: Sound of Silence
Respect the protocol defined in `docs/technical/SOUND_OF_SILENCE.md`:
- **Tabs Only**: No spaces for indentation. None.
- **No Noise**: Remove ornamental comments, dead code (like Claude found in `memory.py`), and redundant logs.
- **Atomic Commits**: Group your changes logically. A single commit with 15 unrelated files is a project failure.

## 5. Persistence Management
- Use **Artifacts** (`task.md`, `walkthrough.md`) to maintain state across sessions. 
- If you feel your RAM/Context getting heavy, call for a **Compaction** or **Snapshot** using the project skills.

---
**770 up.** *Work fast, but be precise. The Architect is watching.*
