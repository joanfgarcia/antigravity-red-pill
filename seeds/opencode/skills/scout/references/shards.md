# Scout shards — register, dedup, consent, ledger (v1.0.0)

## The register: `<workspace>/.cell/shards.json`

```json
{ "shards": [ /* shard.schema.json entries */ ], "last_analysis": "ISO-8601" }
```

- Created on first Scout run in a workspace (same anchor dir as Forge's `state.json`).
- The register is the queue AND the audit log: `OPEN` shards are pending work; `DONE` shards keep their `execution_ref` (the report that proves the fix — Rule 1: shards close with evidence, not with intention).
- Writes are append-style merges (read → dedup → write); a concurrent Forge mission and Scout run never clobber each other's entries (same file discipline as `state.json` checkpoints).

## Shard lifecycle

```
OPEN ──(Operator: "hazlo"/"adelante")──▶ ACCEPTED ──(shard executed, report validated)──▶ DONE
  │                                                                                      ▲
  ├──(Operator: "no procede")──▶ DISMISSED                                              │
  └──(awakening auto-exec)────▶ ACCEPTED (execution_ref recorded) ───────────────────────┘
```

- `OPEN` → `DONE` directly is allowed ONLY with a validated report (`execution_ref`) — the evidence is the transition, never a checkbox.
- `DISMISSED` keeps the finding (audit): a dismissed shard with the same `standard_violated`+`location` is NOT re-created (dedup counts DISMISSED as seen).

## Dedup rule

A new shard is created only if no shard with the same `standard_violated` + `location` exists in state `OPEN`/`ACCEPTED`/`DISMISSED`. Duplicates found during a run are synthesized into the existing entry (append evidence, keep max priority) — the register never grows by repetition.

## Consent derivation (never self-declared)

| Input | → | consent_level |
|-------|---|---------------|
| `priority: critical` | → | `operator` |
| touches production paths | → | `operator` |
| irreversible action (deletes, schema migrations, renames of public API) | → | `operator` |
| anything else | → | `auto` |

The orchestrator (Scout main loop or awakening driver) derives it from the finding context; the lens agent does not decide it.

## Ledger

Shard creation and execution write `usage_ledger.entries[]` (state.json) with `{role: "scout", report: "shards.json", provenance}` — the same provenance v3.1 contract as Forge reports. `gate-check.mjs` of a later Forge assembly surfaces Scout sources in `summary.provenance`.

## Pinned policies (per workspace)

The Operator may pin stricter rules in the register header:

```json
{ "shards": [], "policy": { "auto_exec": false, "blocked_paths": ["/lib", "db/migrations"] } }
```

- `auto_exec: false` → everything is `operator` in that workspace.
- `blocked_paths` → shards whose `location` matches are forced `operator`.
Pinned wins over derivation.
