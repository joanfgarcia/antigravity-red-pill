# The 9 Zero-Trust Rules — Forge v1.0 (opencode port of v3.2)

> Team motto: *"Verifying is executing. If you did not execute it, you did not verify it."*

Doctrine since v2.0. These rules **do not change with escalation level**: they apply identically at L0 (inline), L3 (multi-workflow) and Mission Mode. Since v3.0 they stopped being prose that agents must obey and became **encoded in schemas and gates** (column "Enforcement" per rule).

---

## RULE 1: Verification IS Execution

> A test that verifies "the file exists" IS NOT A TEST.

A REAL test executes the functionality and verifies the OUTPUT:

| ❌ This is NOT verification | ✅ This IS verification |
|---|---|
| `test -f config.json` | `cat config.json \| jq .` (parses and validates JSON) |
| `grep "graphify" .mcp.json` | Restart the session and verify the MCP responds |
| `ls scripts/backup.sh` | `bash scripts/backup.sh && ls -la backup/` |
| `cat README.md \| head -1` | Verify README reflects the REAL state of the project |
| `wc -l tests/` | Run the tests and observe PASS/FAIL |

**Enforcement:** `gate-check.mjs` reclassifies as `INSUFFICIENT` (blocking) every PASS whose evidence matches the anti-trivial pattern (`grep`/`test -f`/`ls`/`wc`/`cat` without a pipe to a real parser or executor).

## RULE 2: Assumption Registry

EVERY technical assumption must be registered (`registry[]` in `.swarm/state.json`, schema `assumption`).

- **What is an assumption?** Anything taken for granted without executing it:
  - *"This field exists in the schema"* → did you check the official docs?
  - *"This app reads from this path"* → did you test it by restarting the app?
  - *"The Chat tab and the Code tab share config"* → did you verify by opening both?
- **States:** `VERIFIED` / `ASSUMED` / `DISPROVEN` / `INVESTIGATING`
- The Devil's Advocate reviews ALL `ASSUMED` before closing
- `ASSUMED` at close = **blocker** to mark the task DONE

**Enforcement:** schema requires VERIFIED/DISPROVEN to carry evidence + `verified_by`, and DISPROVEN to carry `fix_ref`. The gate (check 2) rejects closing with any ASSUMED/INVESTIGATING.

## RULE 3: Plan Coverage Matrix

EVERY plan point → has implementation → has test → has smoke.

- Coverage < 100% → task does **NOT** close
- Exception: `PENDING_HUMAN` items do not block, but must be documented with instructions
- Matrix lives in `coverage[]` of state.json (schema `coverage_entry`); the Documentation Anchor extracts points at start and a **deterministic reducer** updates it after each phase — accounting no longer depends on an agent remembering

**Enforcement:** schema requires CUBIERTO entries to carry `impl_refs`+`smoke_ref`; the gate (check 4) rejects closing with any SIN_CUBRIR.

## RULE 4: End-to-End Smoke before closing

The Smoke Tester executes a REAL user flow before closing.

- **NO** simulations · **NO** "should work" · **NO** "config looks well-formed so it surely loads"
- **YES** execute, observe output, compare with expected
- If E2E is impossible (needs human UI) → `PENDING_HUMAN` with exact instructions

**Protocol by task type:**

| Type | What the Smoke Tester does |
|------|----------------------------|
| **Configuration** | Loads the config in the real app, verifies the system recognizes it |
| **API/MCP** | Makes a real call to the endpoint/tool and verifies the response |
| **Script** | Runs the script and verifies the output is the expected one |
| **UI** | If possible: navigates the UI (preview tools / browser) and verifies. If not: `PENDING_HUMAN` |
| **Integration** | Runs the full cross-system flow and verifies the final state |
| **Config file** | Parses with the real parser (jq, YAML.load...) and verifies structure |

**Enforcement:** schema `smoke_report` makes PASS impossible without `evidence`+`observed`, and PENDING_HUMAN impossible without `human_instructions`.

## RULE 5: Fail-Fast Honesty

If something cannot be verified, it is documented as **NOT VERIFIED**.

- **NEVER** mark `PASS` something that was not really tested
- Better `45/55 PASS, 10 PENDING` than a lie of `55/55 PASS`
- The QA Report ALWAYS shows 3 categories: PASS, FAIL, PENDING_HUMAN
- **Lying about the state of a test is the worst possible team offense**

**Enforcement:** `qa_final.totals` requires all 3 numbers; the COMPLETE verdict is recomputed by the gate — a QA cannot inflate it even by wanting to.

## RULE 6: No "Verified" without Output

Every verification MUST include the **real output** obtained.

- "test passed" is not enough → include what was executed and what it returned
- No output → no execution → no verification

**Enforcement:** `Evidence` (common.defs) makes `command`, `exit_code` and `output_excerpt` mandatory on every PASS/FAIL from every role.

## RULE 7: Environment Segregation

When a system has multiple environments/contexts, ALL are verified separately.

- App with Chat tab and Code tab → verify BOTH
- dev/pre/pro → verify the applicable ones
- Global config and per-project config → verify BOTH
- The Devil's Advocate actively asks: *"Are there more contexts we have not considered?"*

**Shared infrastructure (v3.2, canonizes decision D-11 of the 2026-07 brain mission):** any schema or state change on infrastructure others use (shared DEV DB, queues, brokers) — e.g. Flyway migrations — is validated FIRST in an isolated ephemeral environment (Testcontainers / docker) applying the full chain; **only after green** does it touch the shared environment. A half-failed migration on the shared DEV DB blocks every developer and pod.

**Enforcement:** dedicated `env_segregation` lens in the adversarial panel (always present from L2).

## RULE 8: The Plan is the Law

The original plan is the contract. It does not close until covered.

- If a plan point turns out impossible → document it as `BLOCKED: [reason]` (never silently ignored)
- Unplanned tasks added → documented as `EXTRA`
- The final report compares: original plan vs. implemented reality
- **v3.0 nuance (Mission Mode):** if a better solution exists than the literal plan, apply the best one and register the deviation in `decisions[]` with rationale (Operator's golden rule) — deviating in silence remains forbidden

**Enforcement:** `plan_completeness` lens in the panel; the gate crosses coverage against the anchor plan's extracted points.

## RULE 9: Environment Symmetry Check

> Born from a real incident (2026-06, retired legacy IDE) where 3 core MCPs were missing on one workstation and the team did not detect it because it only verified "doc vs reality" without comparing "platform A vs platform B".

When a system is designed to run on **multiple platforms/IDEs**, verify ALL have **functional parity**.

- If one workstation has the core MCPs → the rest must have the same
- If one platform has rules/skills → the other too (or document why not)
- Any asymmetry is registered as `ASSUMED` until justified

| ❌ Symmetry failure | ✅ Correct parity |
|---|---|
| Workstation A has 5 MCPs, workstation B has 2 | Both have the core MCPs |
| Workstation A launches an MCP with different flags than B | Both use the same canonical invocation |
| A platform has graphify broken and nobody reports it | It is detected, fixed, verified |
| Smoke Tester sees the asymmetry but classifies it as PASS | Asymmetry is escalated as FAIL |

**Enforcement:** `parity_table` field in schema `smoke_report` + `env_segregation` lens questions.

---

## Post-Mortem: The MCP Incident (foundational reference)

> [!WARNING]
> This documents the incident (May 2026) that motivated v2.0. Read it to understand WHY the Zero-Trust rules exist.

**Context:** Integration of Claude Desktop (now-retired environment) with the Azrael ecosystem (MCPs, configs, scripts).

**What happened:**
1. The v1.0 team reported `55/55 PASS` on the test battery
2. The tests verified **file existence**, not behavior
3. The `cwd` field was assumed to exist in Claude Desktop's MCP config — **it does not**
4. Chat tab and Code tab were assumed to share configuration — **they are separate worlds with independent configs**
5. "MCP configured" was assumed to mean "the JSON has the entry" — in reality you must restart the app and verify it appears in the MCP panel

**What v2.0 would have detected:** the Smoke Tester would have tried to load the real config (→ error on `cwd`); the Devil's Advocate would have asked *"do Chat and Code share config?"*; the Documentation Anchor would have seen the plan said "ALL MCPs" while only a subset was verified; Rule 5 would have prevented `55/55 PASS`.

**What v3.0 adds:** v2.0 trusted agents to obey the doctrine. v3.0 makes it **unavoidable**: schemas reject a PASS without evidence and the gate recomputes every verdict from data. The incident goes from "should not repeat" to "cannot validate".

**Lesson:** the v1.0 team was honest but had no mechanisms to detect its own blind spots. v2.0 institutionalized constructive paranoia. v3.0 turned it into code.

---

## Inline auto-challenge (L0)

When the team is collapsed at L0, the Orchestrator applies the Devil's Advocate battery to itself before closing:

- *"What if that field does not exist in this version?"*
- *"What if there are two separate configs and only one was edited?"*
- *"What if the test passes but for the wrong reason?"*
- *"What if the official docs are outdated?"*
- *"What if it works locally but not in production?"*
- *"What if the validator checked the old cached file?"*
- *"Are there more contexts/platforms we have not considered?"* (Rules 7 and 9)

> *"I prefer an honest 80% completion report over a lie of 100%."*
