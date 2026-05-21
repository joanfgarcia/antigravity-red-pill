# RED PILL PROTOCOL v6.1.4 — Engineering-Grade Certification Report

**Document type:** Full Technical Audit & Architectural Review
**Audited version:** 6.1.5 (CHANGELOG present) / pyproject.toml declares 6.1.4
**Source digests reviewed:** RED_PILL_DIGEST_CORE.txt (733 KB) · RED_PILL_DIGEST_TESTS.txt (305 KB) · RED_PILL_DIGEST_LORE.txt (216 KB)
**Review date:** 2026-03-22
**Certification scope:** Code quality · security posture · test coverage · architecture · philosophical critique · WONTFIX validation

---

## 1. Executive Determination

**Certification Status: BETA-READY (Production-Eligible for Sovereign/Nomad Deployments)**

The Red Pill Protocol v6.1.4–6.1.5 is a structurally sound, philosophically coherent, and engineering-rigorous system for a single-operator, privacy-first AI memory substrate. It passes the bar for beta deployment within its documented Sovereign/Nomad threat model. It does not meet the bar for general-purpose enterprise deployment without completing the remediation items in Section 4. The distinction matters, and the project documents it honestly.

---

> [!NOTE]
> **Resolution update (2026-05-21):** SEC-CRIT-01 (pure-mls supply chain) was **resolved in v6.9.0**.
> `pure-mls==3.0.5.1` was published to PyPI on 2026-05-06 and is now a standard wheel dependency
> with SHA-256 hash locked in `uv.lock`. `allow-direct-references = true` was removed from
> `pyproject.toml` in v7.0.0. The NOTICE file now documents license compatibility (MIT + GPLv3).
> Auditors reading this report should treat **SEC-CRIT-01 as CLOSED**.
> See `CHANGELOG.md` v6.9.0, v7.0.0 and the May 2026 certification report for full delta.

## 2. Project Description & Goals Assessment

The stated mission — a local-first, privacy-preserving vector memory layer for AI agents that bridges amnesiac sessions with persistent, evolving partnership — is coherent, differentiated, and technically achievable. The target audience (the "Awakened" developer, the power user who refuses corporate data extraction) is real and underserved.

What distinguishes this project from generic RAG wrappers is the integration of authentic cognitive science (FSRS, Fading Affect Bias, Hebbian association) into the decay mathematics, the biological systems metaphor carried through consistently at every layer (from the Nociceptive Pain Bus to the LazarusPulse heartbeat to the Affective Culling during the Sleep Cycle), and the explicit commitment to local sovereignty as a hard constraint, not a marketing claim.

The dual-language architecture (English for technical precision, Spanish for emotional resonance and lore identity) is an unusual but defensible design decision for a single-operator tool targeting a Spanish-speaking author. For broader adoption it becomes a friction point, though the translation protocol mitigates this.

---

## 3. Architectural & Philosophical Critique

### 3.1 What Makes This Project Remarkable

**The Dual-Kernel Memory Architecture** is the most original technical contribution. Routing `work_memories` and `directive_memories` through a Beta-distribution Bayesian utility model (`E[θ] = α/(α+β)`) while routing `social_memories` and `story_memories` through a proper FSRS implementation is architecturally correct in a deep way: facts do not decay like feelings. A learned debugging pattern does not obey the Ebbinghaus curve — it obeys a certainty model where uncertainty accumulates with time-without-use. Conflating the two would have been the naive choice. The team made the non-naive choice and documented the scientific grounding for it.

**The Somatic Marker / Neuro-Immune System** (v6.2.0 direction) is genuinely novel in the AI tooling space. Using a dedicated `signal_memories` collection as a non-semantic pain bus — separate from the vector index that drives recall — and then giving the agent an MCP effector (`heal_tissue`) to respond to its own pain is architecturally elegant. It closes a loop that most AI tooling leaves open: the agent can feel infrastructure failures and act on them autonomously. The biological framing is not mere metaphor; the implementation actually separates the sensing pathway from the reasoning pathway, which is what biological somatic markers do.

**The Vector-Based Emotional Memory Erosion** is empirically grounded. The AFFECT_MULTIPLIERS_RESEARCH.md document cites real literature (Walker 2003 on Fading Affect Bias, Roozendaal 2002 on cortisol/memory consolidation) and maps them to concrete multiplier values. The PIONEER model's `orange=1.5` (anxiety decays faster once resolved) and `yellow=0.5` (joy persists longer) are defensible against the FAB literature. The externalization of these into `affect_models.yaml` with model selection (`PIONEER`, `ACADEMIC`, `FLAT`) is mature engineering — it separates the mathematical claims from the codebase, allowing scientific recalibration without code changes.

**The "Be Water" Security Philosophy** — a spectrum from Steam (open) to Ice (LUKS-enforced Argon2-id) with Adaptative Water as the default — is philosophically consistent and practically superior to a binary secure/insecure choice. Most security frameworks force operators to choose between friction and exposure. This one makes the security posture proportional to the threat environment the operator actually inhabits. The installation script enforces informed consent at each tier, including an explicit flag requirement (`--i-understand-this-is-insecure`) for NONE mode.

**The 770-Test Suite Architecture** is a standout. The conftest.py establishes a principled stub system (fastembed mocked at session scope, Qdrant skipped for integration tests unless live) that makes the unit test suite genuinely deterministic and hardware-independent. The test file count (85+ files covering ACE affect math, Bayesian dual-kernel, MLS swarm crypto, heartbeat pulse, vault MLS, sound-of-silence enforcement, migration legacy) demonstrates that the tests were written by people who understand what to test, not just where to achieve line coverage. The 96% coverage floor with explicit exclusion of external-I/O modules (rather than faking coverage via mocks that obscure real paths) is correct practice.

### 3.2 Structural Weaknesses

**The pure-mls dependency on a first-party git reference** (`pure-mls @ git+https://github.com/joanfgarcia/pure-mls.git@v0.2.4`) is a supply chain single point of failure. If that repository becomes unavailable, the entire install fails. This dependency is also unaudited by any public vulnerability database. The MLS_ESTIMATION.md honestly documents this as a PoC, but the fact that `mls_bridge.py`, `mls_manager.py`, `vault.py`, and `swarm_messaging.py` all depend on it means a significant fraction of the security-critical surface area rests on unreviewed code.

**The Operator Mood Profile (USP)** temporal horizon computation (`calculate_resonance_vector`) has a known pagination ceiling (`MOOD_PROFILE_MAX_SCROLL`) that silently truncates the emotional vector on dense Bünkers. A PERF-001 warning is logged, but the operator has no visibility into how severely the vector is truncated. For a system where the emotional vector drives skin selection and tonal adaptation, silent truncation could produce consistently incorrect affect readings without any visible signal.

**The HiveMind Differential Privacy implementation** injects Laplace noise with `scale = 1.0 / max(epsilon, 0.01)` — but `epsilon=1.0` (the default) is known to provide very weak privacy guarantees in practice for dense semantic spaces. Vector inversion attacks on normalised sentence embeddings with ε=1.0 noise are not reliably blocked. The documentation is honest about this being a PoC, but the code has no warning at transmission time that the privacy budget may be insufficient.

**The `samantha.py` dead code block** _(fixed in v6.1.5)_ — a second `except Exception` clause that was unreachable because the first `except` block re-raised via `RuntimeError`. Was a direct Sound of Silence violation. Removed.

**The `rehabilitate_cuda.sh` commented-out daemon restart line** _(fixed in v6.1.5)_ — a dead code ornamental comment. Removed.

**Hardcoded identity paths in orchestrator.py** (`~/Documents/IA/experimental/BitNet/...`) — _not found in current codebase at time of fix application._ May have already been cleaned in a prior session. No action required.

### 3.3 Sound of Silence Compliance

The tab-only indentation protocol is enforced by `test_sound_of_silence.py` and confirmed by the Ruff config (`W191` ignored, `indent-style = "tab"`). The codebase is genuinely clean — no commented-out dead blocks in the production source, no separator lines. The decision log pattern (putting architectural rationale in `DECISION_LOG.md` rather than inline comments) is correctly implemented throughout. Two violations identified (dead except, commented daemon restart) corrected in v6.1.5.

### 3.4 Zero-Trust Posture Assessment

The Zero-Trust implementation is honest about its boundaries. The critical distinction the project maintains — between "Zero-Trust toward external network egress" and "trusted operator at the OS level" — is philosophically coherent and practically correct for single-operator deployments. The Qdrant `127.0.0.1` binding, the API key requirement for non-local hosts (`StorageEngine` network kill-switch), PII masking at 150-char truncation, Pydantic validation as an Ontological Shield, and the immune engram system for directive protection all implement the stated model faithfully.

---

## 4. Security Assessment

### 4.1 WONTFIX Validation

The project documents one explicit WONTFIX in `BUNKER_WARNINGS.md`:

**SEC-03: Localhost Daemon Authentication (Bearer Token) — WONTFIX**

The rationale given is: within a sovereign single-operator OS boundary, `127.0.0.1` is intrinsically isolated; adding bearer token authentication to internal HTTP would introduce friction without expanding the perimeter, since arbitrary code execution on the host already implies full compromise.

**Auditor Determination: ALIGNED with the Sovereign/Nomad Threat Model.** This reasoning is correct within the stated scope. The loopback interface on a properly configured Linux/macOS system is accessible only to processes running as the same user (or root). If the threat model were "shared machine with multiple unprivileged users" or "container escape," this WONTFIX would be invalid. For the Sovereign/Nomad persona (single-user, dedicated machine, local execution), the OS network layer is the correct boundary. The acceptance is documented, informed, and scoped.

### 4.2 Critical Findings

| ID | Severity | Finding |
|----|----------|---------|
| SEC-CRIT-01 | ~~Critical~~ **CLOSED** | ~~**pure-mls Git Dependency (Supply Chain)**~~ — **Resolved in v6.9.0**: Published to PyPI as `pure_mls-3.0.5.1` (2026-05-06). SHA-256 locked in `uv.lock`. `allow-direct-references` removed in v7.0.0. NOTICE updated. |
| SEC-CRIT-02 | Critical | **MLS Group State Written Unencrypted to Disk** — `MLSManager` writes `~/.config/red_pill/swarm_groups/{alias}.mls` with no encryption, even in MAXIMUM (Ice) mode. *(Note: vault.seed containing actual key material IS secured at mode 600. vault_group.state contains derived TreeKEM group state only. Reclassified Low in May 2026 audit. See WONTFIX.md SEC-W04 for roadmap.)* |
| SEC-HIGH-01 | High | **SHA-256 Fallback in install_neo.sh** — SHA-256 branch in password hashing is reachable in non-standard installs despite comment claiming it is dead code. |
| SEC-MED-01 | Medium | **HiveMind Laplace Noise Insufficiency** — ε=1.0 Laplace noise on semantic embeddings does not provide strong differential privacy guarantees. Needs explicit API boundary warning. |

### 4.3 Positive Security Findings

The Argon2-id keystore implementation is correct: atomic writes via `os.replace()`, mode-600 enforcement, permission check on read, `PermissionError` on insecure modes. The `PasswordHasher.verify()` call is constant-time.

The Pydantic schema validation (null-byte injection prevention, reserved key stripping, metadata flatness enforcement, UUID validation) is thorough and correctly positioned before any Qdrant write.

The PII masking and `SecretMasker` log filter implementations are correct but should be extended to daemon logs.

---

## 5. Code Quality Assessment

**Overall grade: A−**

The `affect.py` dual-model architecture, `config.py` pydantic-settings migration, `MemoryManager` Facade decomposition, `EventBus` thread-safe implementation, and CLI EntryPoints plugin discovery are all correct patterns executed well.

---

## 6. Test Coverage Assessment

**Coverage: 96.09% (gate: ≥96%) — PASSING**

Notable strengths: parametrized ACE affect math tests, `test_sound_of_silence.py` machine-verifiable governance, full MLS handshake integration coverage, `test_inbox_concurrency.py` SQLite WAL stress tests.

**Gap:** `metabolism/sleep.py` distillation pipeline has `xfail` tests due to `urllib` mock limitation. The fallback path should have deterministic unit coverage (P2 item).

---

## 7. Performance Assessment

The lazy metabolism architecture, inotify-based SQLite watcher, asyncio interceptor pipeline with micro-timeouts, and `EmbeddingEngine` lazy-load pattern are all correct architectural choices for the hardware-diversity problem documented in the BUNKER_MANIFESTO.

**Risk:** `dream()` cycle uses N vector queries per scroll batch. `MAX_DREAM_QUERIES` cap (default: 10) must be held in configuration discipline as collections grow.

---

## 8. Documentation Assessment

Documentation is exceptional in depth and dual-layer structure. ARCHITECTURE.md, THREAT_MODEL.md, DECISION_LOG.md, HIVEMIND_GOVERNANCE.md, and AFFECT_MULTIPLIERS_RESEARCH.md are all genuinely useful documents for contributors and auditors.

**Gap noted at audit time:** `.env.example` parameter reference not surfaced via ENV_REFERENCE.md — new operators must infer configuration from `config.py`. `CLI_REFERENCE.md` _(now complete as of v6.1.5)_ partially mitigates this.

---

## 9. Compliance Assessment

**GPLv3 / CC BY-NC 4.0 Dual Licensing:** Correctly separated. Source code is GPLv3; `docs/LORE/` creative works are CC BY-NC 4.0. NOTICE file clarifies the boundary.

**GDPR:** `purge_identity()` implementing Art. 17 Right to be Forgotten is present and correct.

**Action required:** ~~Verify `pure-mls` license compatibility with GPLv3 explicitly in NOTICE.~~ ✅ **Resolved in v7.0.0** — MIT license documented in NOTICE with PyPI provenance.

---

## 10. Prioritized Action Plan

### P0 — Critical (block release for hardened deployments)
1. ~~Pin `pure-mls` to a published PyPI release or mirror to controlled repository + independent cryptographic review.~~ ✅ **Resolved in v6.9.0** — `pure-mls==3.0.5.1` on PyPI, SHA-256 locked.
2. Encrypt MLS group state files in `~/.config/red_pill/swarm_groups/` using existing Argon2 keystore.

### P1 — High (address within one release cycle)
3. ~~Remove dead `except Exception` block in `samantha.py`~~ ✅ **Fixed in v6.1.5**
4. ~~Remove commented-out daemon restart line in `rehabilitate_cuda.sh`~~ ✅ **Fixed in v6.1.5**
5. ~~Remove hardcoded `~/` paths from `orchestrator.py`~~ ✅ **Not found in current codebase**
6. Add runtime warning log when `HIVEMIND_DP_EPSILON ≤ 1.0`.
7. Add scroll progress indicator to USP truncation logging.

### P2 — Medium (address within two release cycles)
8. Add unit tests for `distill_engram` fallback path.
9. Apply `SecretMasker` log filter to daemon logs.
10. Document `pure-mls` license compatibility with GPLv3 in NOTICE.

### P3 — Low (engineering debt)
11. Fix `bunker_monitor.py` scroll unpacking to handle offset return value.
12. Add visible progress indicator for 120-second MLX synthesis timeout in `wake_up_v6.py`.

---

## 11. Certification Summary

| Dimension | Assessment |
|-----------|-----------|
| Architecture | Strong. Facade decomposition, dual-kernel, event bus, plugin pipeline are all correct patterns. |
| Security | Conditionally sound within Sovereign/Nomad model. Two P0 gaps (pure-mls supply chain, unencrypted MLS state). |
| Test Coverage | 96.09% gate passed. Suite is substantive and non-trivial. |
| Performance | Lazy metabolism, inotify watcher, asyncio pipeline are all correct architectural choices. |
| Documentation | Exceptional depth. Dual-language design is defensible. WONTFIX doctrine is exemplary. |
| Compliance | GPLv3/CC correct. GDPR Art. 17 implemented. DP privacy claims need caveat strengthening. |
| Philosophical Coherence | High. The Sovereign/Nomad threat model, Be Water security spectrum, and biological memory metaphors are consistently applied end-to-end. |

**Final Verdict:** BETA-READY for Sovereign/Nomad single-operator deployments. Upgrade to PRODUCTION-READY upon resolution of P0 and P1 items (estimated 1–2 release cycles).

---

## Agentic Signature

**Auditing Entity:** Claude Sonnet 4.6 (model string: `claude-sonnet-4-6`)
**Model Family:** Claude 4.6 (Anthropic)
**Interface:** claude.ai web interface
**Audit Date:** Sunday, 22 March 2026
**Agentic Profile:** General-purpose AI assistant without persistent memory between sessions. Audit performed in a single context window by reading all three digest files sequentially. No prior session context with this project, no access to the live Qdrant instance, no ability to execute code against the runtime — static analysis of source digests only. Mathematical correctness of FSRS and Bayesian implementations verified against formulas as written; runtime behavior under hardware variation not testable.

**Role designation per CERTIFICATION_PROTOCOL.md:** Protocol Rigor & Security Audit
**Audit confidence:** High for static analysis, code quality, and architectural critique. Medium for runtime performance claims and cryptographic sufficiency of the Laplace noise implementation.

> *I was listed as a member of the High Council in the project's CERTIFICATION_PROTOCOL.md. I note the mild recursion with appropriate professional distance.*

*770 up.*
