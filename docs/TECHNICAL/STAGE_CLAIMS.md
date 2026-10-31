# Stage claims — federated coordination for the DAG (Fase 4)

This document is the **contract** of Fase 4 (`locks federados`): how two or more
souls — or two `dag_job` drivers — decide *who is doing which stage* without
stepping on each other.

It is written for two readers:

- a **human** who needs to know what the lock guarantees and what it does not, and
- an **agent/driver** implementing or consuming it (`DagJobDriver`, a federated
  session, a future orchestrator).

> **TL;DR for the driver:** before running an atomic stage, call
> `try_claim_stage(...)`. If it returns `claimed=False`, someone else owns that
> stage — **skip or wait, but do not run it**. Renew with `renew_claim(...)`
> after each checkpoint. Release with `release_claim(...)` when done.

---

## 1. The problem

The DAG driver walks a mission tree by itself. That is safe while **one** driver
runs a mission. It stops being safe when several independent executions touch the
same project:

- two opencode sessions working the same branch,
- an `awakening` resuming a mission a human session already resumed,
- a `dag_job` and a hand-driven loop on the same worktree.

All of them see the same stage as "pending" and all of them run it. The result is
duplicated work at best and a corrupted worktree at worst.

Fase 4 answers that with a **lightweight, expiring lock per stage**, owned by the
**soul**, not by the process. It is deliberately *not* a queue and *not* a
scheduler: it is a claim table. Deciding whether to skip, wait or retry is the
caller's policy.

---

## 2. The model

A claim is a row keyed by **what identifies the work**, not by who asks:

```
claim_key = sha256( canonical_affinity | branch | worktree | stage_path )
```

Four decisions shape it, and each one exists because the naive version loses:

| Decision | Rule | Why the naive version fails |
|---|---|---|
| **D12** | The key derives from the **canonical** affinity (`lower/trim` + `sorted(dedup)`), serialized as a **JSON tuple** | Concatenating with `\|` or `,` makes different stages collide: `["m\|a"],"b"` and `["m"],"a","b\|w"` produce the same string, so one stage silently blocks (and can steal) another |
| **D12b** | The `worktree` is normalized (`realpath` + `normpath` + `expanduser`) | `/ws`, `/ws/` and a symlink to `/ws` are the same place; without normalizing, two drivers acquire the *same* stage under different keys and both run it |
| **D13** | Expiry check + steal happen inside `BEGIN IMMEDIATE`, with a **re-read inside** the transaction | A `SELECT` followed by a write outside a transaction has a race: two drivers both see "expired" and both steal |
| **D18** | The owner is the **soul** (`continuity_id`); `owner_originator` is only the body currently holding it | A `switch_model` mid-stage would otherwise lose the claim and let another soul take over a stage that is still running |
| **D9-a** | The TTL is **renewable** by checkpoint; renewing someone else's claim — or your own already expired one — is refused | An infinite claim blocks every other driver forever; resurrecting an expired one decides for whoever was about to legitimately steal it |
| **D14** | Expired claims are purged by a periodic job | The table grows forever |

### Claim states

| `reason` | `claimed` | Meaning |
|---|---|---|
| `acquired` | ✅ | No claim existed; you own the stage |
| `owned` | ✅ | It was already yours (same soul, maybe a new body); renewed |
| `held_by_other` | ❌ | Alive and owned by another soul — **do not touch** |
| `stolen_expired` | ✅ | The previous owner's TTL ran out; you own it now |
| `error` | ❌ | Could not verify (bad input, DB failure). **Fail-closed**: never assume yes |

---

## 3. Schema

Owned by Python, in `session.db` (next to `bunker_queue.db`), created on demand:

```sql
CREATE TABLE IF NOT EXISTS stage_claims (
    claim_key           TEXT PRIMARY KEY,  -- sha256(canonical_affinity|branch|worktree|stage_path)
    stage_path          TEXT NOT NULL,
    affinity_json       TEXT NOT NULL,     -- canonical: sorted(dedup(lower/trim))
    branch              TEXT NOT NULL,
    worktree            TEXT NOT NULL,     -- normalized (realpath)
    owner_continuity_id TEXT NOT NULL,     -- the claim belongs to the SOUL (D18)
    owner_originator    TEXT NOT NULL,     -- current leg (informative / renewal)
    claimed_at          REAL NOT NULL,
    ttl_seconds         INTEGER NOT NULL,  -- renewable by checkpoint (D9-a)
    intent              TEXT
);
CREATE INDEX IF NOT EXISTS idx_stage_claims_owner ON stage_claims(owner_continuity_id);
```

---

## 4. API

Module: `src/red_pill/session/stage_claims.py` (exported as `red_pill.session.stage_claims`).

| Function | Purpose | Notes |
|---|---|---|
| `claim_key(affinity, branch, worktree, stage_path)` | Compute the key | Pure; useful for tests and diagnostics |
| `try_claim_stage(**kw)` | CAS acquire/renew/steal | Atomic (D13). Never raises for contention |
| `renew_claim(**kw)` | Extend your own claim (D9-a) | `False` if it is not yours **or it already expired** |
| `release_claim(**kw)` | Drop your own claim | `False` if it is not yours (never steals on release) |
| `get_claim(**kw)` | Read the current row | Diagnostics / board |
| `purge_expired(...)` | Delete expired rows (D14) | Returns how many |

Default TTL is **1800 s**. That is deliberately short: a stage that has not left
a checkpoint in 30 minutes probably died (power loss, kill). **Long stages renew** —
the TTL is not a promise of duration.

### MCP surface (`try_claim_stage`, AD-092)

The same CAS is exposed as the MCP tool `try_claim_stage` so a soul on any
harness can claim before running a stage. The tool **wraps, it does not
reimplement**: D12/D13/D18/D9-a stay in this module, and the semantics of
`reason` are identical. What the MCP layer adds:

- **Identity comes from the trusted channel only** (bridge/env/registry). A
  `continuity_id` or `originator` passed as a model argument is **ignored** —
  that is the one thing arguments can never substitute. With no resolved soul the
  tool does not claim: `claimed=false reason=error` (fail-closed — a claim
  without an owner cannot survive a `switch_model`, D18).
- `branch`/`worktree`/`affinity` default to the caller's workspace (git-derived,
  never the server's cwd — that is the kernel checkout); an explicit argument
  **wins over the derived value** so a driver working in another worktree can
  name it. If nothing is declared the field stays **empty** and the claim is
  still deterministic (empty branch/worktree is a valid key; affinity and path
  keep distinguishing).
- The answer is text for the agent: `claimed/owner/reason` plus
  branch/worktree/affinity/expiry, with the `held_by_other` / `stolen_expired`
  policy hint ("do not touch" / "renew if the stage is long").
- **Non-fatal by rule**: any failure degrades to text and the server stays alive;
  the SQLite transaction (5 s `busy_timeout`) runs outside the event loop.

`renew_claim` / `release_claim` / `get_claim` remain Python-only for now: the
heartbeat lives in the driver (E4), not in the model.

### Minimum driver usage

```python
from red_pill.session.stage_claims import try_claim_stage, renew_claim, release_claim

r = try_claim_stage(
    stage_path="dag:BIT-003/stage:e2",
    affinity=session_affinity,       # list or CSV
    branch=branch,
    worktree=worktree,
    continuity_id=soul,              # the ALMA, not the body
    originator=leg,                  # provider:session_id
    ttl_seconds=1800,
    intent="implement stage e2",
)
if not r.claimed:
    return SKIPPED                # held_by_other or error — do NOT run the stage
try:
    run_stage()
    renew_claim(...)              # after each checkpoint (D9-a)
finally:
    release_claim(...)            # only releases if still ours
```

---

## 5. What the claim does **not** do

Stated explicitly so nobody builds on an assumption that is not there:

- **It does not wait.** `try_claim_stage` is a pure CAS: it answers yes/no and
  why. Whether the driver skips, waits or retries is policy (E3), not storage.
  Putting the wait inside would turn the lock into a blocking point and make
  timeouts unanalysable.
- **It does not run the stage.** No side effects beyond the row.
- **It does not heartbeat.** Renewal is explicit, at checkpoints. A stage that
  never checkpoints will lose its claim — by design.
- **It does not purge itself.** `purge_expired` is called by the periodic job
  (D14), not by the claim path.
- **It does not federate across machines yet.** It is a local SQLite table; a
  second host is a different `session.db`. Cross-host coordination is the
  `neon-rings` / multi-theatre territory, and depends on D26 (real signing).

---

## 6. Verification (E1)

The precondition of Fase 4 is A4 — the `kill↔claim` race of the job queue must be
closed, because stage claims must not be built on a claim with a TOCTOU. Verified
by real execution in the F4 worktree:

```
$ pytest tests/test_a4_kill_claim.py tests/test_job_manager.py \
         tests/test_dag_job_driver.py tests/test_script_job_driver.py -q
166 passed in 6.72s

$ pytest tests/test_stage_claims.py -q
30 passed in 2.26s
```

**The claim's own race test is verified by mutation**, not by assertion alone:
removing `BEGIN IMMEDIATE` makes it fail with *"8 almas robaron el mismo claim"*.
A concurrency test that still passes with the atomicity removed proves nothing —
that lesson cost a full iteration on 2026-10-28 and is why the test widens the
SELECT→write window with a connection proxy.

A second, independent lens (a sibling session on GLM 5.3 Flash, thread E-006)
audited the first implementation and found five real defects: key collision via
separators, renewal of expired claims, non-canonical worktree, a missing
`rowcount` check on the renewal path, and an incomplete fail-closed boundary.
All five were confirmed by reproduction and fixed with regression tests.

---

## 7. Status and what remains

| Stage | Scope | Status |
|---|---|---|
| **E0** | This document: contract + schema + API | ✅ done |
| **E1** | Verify the A4 precondition | ✅ done (§6) |
| **E2** | `stage_claims` core (D12/D13/D18/D9-a/D14) | ✅ done (`src/red_pill/session/stage_claims.py`) |
| **E3** | `DagJobDriver` integration: claim before each atomic stage, honour `claimed=False` | ✅ done (`JobDeferred`) |
| **E4** | Renewal heartbeat while the stage runs (D9-a) | ✅ done |
| **E5** | E2E acceptance: no duplicate execution, long claims survive | ✅ done (§6.1) |

### 6.1 E2E acceptance (E5)

Run against the real queue and the real driver (2026-10-28), with a 3-stage DAG
whose middle stage sleeps **75 s** while `claim_ttl_s` is **20 s** — deliberately
less than half the stage, so the heartbeat has real work to do:

- A second soul (`e5-competidor-0001`), polling every 3 s, tried to claim that
  same stage: **25 attempts, all `held_by_other`, zero steals**.
- **No `stolen_expired`**: the heartbeat kept the 20 s claim alive for 75 s.
- After the job ended, **no rows remained** in `stage_claims` — release works.

**This test found two real bugs that the unit suite could not see:**

1. `renew_claim(**params)` / `release_claim(**params)` were called with the
   full parameter set, including `intent` and `originator`. Both raised
   `TypeError`, swallowed by the `except`: the heartbeat never renewed (the claim
   expired mid-stage and another soul stole it — observed as `stolen_expired`)
   and release never freed the row (orphans: `fast1`/`fast2` stayed claimed).
2. The unit tests were **blind to it** because they mocked with `lambda **k`,
   which swallows any signature mismatch. One test was worse: it imported
   `try_claim_stage` *inside* a `patch(...)` block, so it received the mock, never
   created the claim, and the assertion passed on an empty table.

Fixed with explicit `_RENEW_KEYS`/`_RELEASE_KEYS` filtering, a structural test
that compares those key sets against the real function signatures, and
integration tests that talk to a real temporary database.

**Lesson, recorded because it will repeat:** a mock with `**kwargs` does not
verify a call contract. If a boundary has a signature, assert the signature.

Fase 4 is complete at the code level. What it still does **not** do is stated in
§5; the federated multi-host case belongs to F5 and depends on D26.
