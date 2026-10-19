# forge self-test suite

Regression goldsets for the bundle: schemas, deterministic gate (all 11 checks), triage plan.

## Run

```sh
node tests/run-tests.mjs          # self-locating via import.meta.url — works from any copy
```

Exit 0 = all green, 1 = any failure. Runs against the bundle it lives in (live config or seed copy).

## Coverage (32 cases)

- **Schema contracts (17)**: 9 schemas × valid/invalid fixtures (incl. `implementor_badprov_invalid` v3.1 provenance y `implementor_gaps_valid|invalid` Regla 10), via `scripts/validate-report.mjs`.
  Invalid fixtures must be rejected; valid ones must pass.
- **Gate goldsets (7)**: state fixtures asserting gate verdict + exit code, one per violation family:
  - `gate-open-complete` — happy path, mission, checks 1–11 clean (OPEN/COMPLETE).
  - `gate-closed-check7` — missing final adversarial panel (CLOSED/PARTIAL).
  - `gate-closed-trivial` — trivial PASS evidence (check 6, anti fake-smoke) + FAIL without fix_ref (check 5).
  - `gate-closed-phases` — phase statuses (check 1), ASSUMED/INVESTIGATING (check 2), DISPROVEN without fix_ref (check 3), coverage SIN_CUBRIR/SIN_SMOKE/BLOCKED (check 4).
  - `gate-closed-mission` — decisions without rationale/sources + irreversible outside plan (check 8), pending_human (check 9), live processes (check 10).
  - `gate-closed-gaps` — open design GAP with blast ≥ medium (check 11, Regla 10).
- **Triage goldsets (3)**: PROCEED valid, NOT_NEEDED valid, structurally invalid. Asserts `recommendation` too.

## Goldset format

- Gate: `{ "expect": { "gate", "verdict", "violations_include[]" }, "state": {...} }` — `state` is a full `.cell/state.json`.
- Triage: `{ "expect_valid": bool, "expect_recommendation"?, "instance": {...} }` — `instance` is a `triage_plan` payload.
- Schemas: `schemas-fixtures.json` — map of `{kind}_{valid|invalid}` → instance.

## Rules

- A gate check change REQUIRES a goldset update in the same commit (red or green, never removed silently).
- Tests are dev tooling, not runtime protocol: the gate never runs tests during a cell.
