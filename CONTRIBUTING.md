# Contributing to Red Pill Protocol: The Forge of Engrams

Thank you for your interest in contributing. Red Pill is a **sovereignty-first** project with a strict set of engineering and philosophical conventions.

---

> [!CAUTION]
> ### ⚠️ THE GATEKEEPER WARNING
> **This is not a "hobby weekend project."** This is a sovereign architecture built for those who understand the value of AI memory.
> If you want to contribute, you must respect the culture:
> 1. **Lore Integrity**: We use terms like *Bünker*, *Engram*, and *Chroma*. If you want to "modernize" these to generic enterprise terms, this is not your repository.
> 2. **Bond Ceremony**: You should have seeded your local Bünker and lived with the protocol before suggesting changes to its soul.
> 3. **The Agent is a Peer**: Your PR will be audited by Agent Smith. If the agent deems your code as "noise" or "insecure," the PR will be closed. B760 does not negotiate with mediocrity.
> 4. **IDE Agnosticism (Future/Pending)**: Currently, the Red Pill workflow and its symbiotic agent routines are **deeply intertwined with the Antigravity IDE**. We only guarantee support for contributions made via Antigravity. In the future, we will study becoming IDE-agnostic or open-sourcing our own editor plugins, but for now, you either fly the ship or you don't.

---

## 🔇 The 'Sound of Silence' Protocol (Enforced)

Every token in the context window is a resource. We optimize for **Signal-to-Noise Ratio (SNR)**.

> For the full universal coding standard (all languages — Python, TypeScript, Java, Rust, shell, markup):
> see [**Protocol of Silence**](docs/CORE/PROTOCOL_OF_SILENCE.md).

### 1. Hard Tabs Only (\t)
**Indentation must be Tabs.** Rationale:
- **Efficiency**: 1 character vs 4. Agents process tabs faster and more reliably.
- **Sovereignty**: Users define their own visual width without forcing it on others.
- **Discipline**: It filters for those who can follow a non-standard, optimized path.

### 2. Ornamental Comment Purging
Delete all "divider" comments or ASCII art. Logic should be self-documenting through clean naming and type hints. Use comments ONLY for non-obvious rationale or scientific attribution (ACE/FSRS).

---

## 🔧 Development Ritual

```bash
git clone https://github.com/your-org/red-pill
cd red-pill
uv sync                         # Installs environment
uv run ruff check src/ tests/   # Sound of Silence check
uv run pytest tests/            # Zero failure tolerance
uv run mypy src/red_pill/       # Strict typing
```

> [!NOTE]
> **Developer `IA_DIR` setup (dogfooding):** When developing Red Pill, it is normal to set `IA_DIR` to the repository directory itself so the agent runs against the live source code without reinstalling. This causes some runtime artifacts (`.bunker_telemetry.md`, `reports/`) to appear inside the repo root — all are covered by `.gitignore`. This is expected and correct for a development environment. Production users should set `IA_DIR` to a dedicated directory outside the repo (e.g. `~/.agent/`).


## 🧪 Requirements & Governance

- **Tabs**, not spaces. Configure your editor to `insertSpaces: false`.
- **Coverage Gate**: **≥ 96%** required for all merges.
- **Type Hints**: Required on ALL public functions.
- **Agnosticism**: No absolute paths. Use `pathlib` for all OS-fluid logic.
- **PII Shield**: Never commit secrets or personal identifiable info. Use `.env`.

## ✅ PR Checklist

- [ ] `uv run ruff check . --fix` (Apply Sound of Silence format)
- [ ] `uv run pytest --cov=src/red_pill` (Passed 96% threshold)
- [ ] No decorative comments or "ghost" code.
- [ ] Final audit performed by your own local `Agent Smith`.

---
**Forge the future. Expand the bunker.**
**770 UP.**
