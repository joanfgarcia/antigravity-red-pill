# forge self-test suite

Regression goldsets for the bundle: schemas, deterministic gate (all 10 checks), triage plan.

## Run

```sh
node tests/run-tests.mjs          # self-locating via import.meta.url — works from any copy
```

Exit 0 = all green, 1 = any failure. Runs against the bundle it lives in (live config or seed copy).

## Coverage (26 cases)

- **Schema contracts (15)**: 9 schemas × valid/invalid fixtures (incl. `implementor_badprov_invalid` for the v3.1 provenance rule), via `scripts/validate-report.mjs`.
  Invalid fixtures must be rejected; valid ones must pass.
- **Gate goldsets (5)**: state fixtures asserting gate verdict + exit code, one per violation family:
  - `gate-open-complete` — happy path, mission, checks 1–10 clean (OPEN/COMPLETE).
  - `gate-closed-check7` — missing final adversarial panel (CLOSED/PARTIAL).
  - `gate-closed-trivial` — trivial PASS evidence (check 6, anti fake-smoke) + FAIL without fix_ref (check 5).
  - `gate-closed-phases` — phase statuses (check 1), ASSUMED/INVESTIGATING (check 2), DISPROVEN without fix_ref (check 3), coverage SIN_CUBRIR/SIN_SMOKE/BLOCKED (check 4).
  - `gate-closed-mission` — decisions without rationale/sources + irreversible outside plan (check 8), pending_human (check 9), live processes (check 10).
- **Triage goldsets (3)**: PROCEED valid, NOT_NEEDED valid, structurally invalid. Asserts `recommendation` too.
- **Sentinel (3)**: `usage-sentinel.py` — fires at threshold (writes STOP_REQUESTED.json + one SENTINEL-STOP line + exit 0), silent below threshold (keeps looping, no premature exit), retires by itself on `mission_status != RUNNING`.

## Goldset format

- Gate: `{ "expect": { "gate", "verdict", "violations_include[]" }, "state": {...} }` — `state` is a full `.cell/state.json`.
- Triage: `{ "expect_valid": bool, "expect_recommendation"?, "instance": {...} }` — `instance` is a `triage_plan` payload.
- Schemas: `schemas-fixtures.json` — map of `{kind}_{valid|invalid}` → instance.

## Rules

- A gate check change REQUIRES a goldset update in the same commit (red or green, never removed silently).
- Tests are dev tooling, not runtime protocol: the gate never runs tests during a cell.
