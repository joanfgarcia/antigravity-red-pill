# 🔴 BÜNKER COMMAND LINE INTERFACE

> **Invocation**: `red-pill [--url QDRANT_URL] [--verbose] <command>`

---

## Global Flags

| Flag | Description |
|------|-------------|
| `--url URL` | Override Qdrant URL (default: from `.env`) |
| `--verbose` | Enable debug logging |

---

## Commands

### `seed` — Initialize memory substrate
```bash
red-pill seed
```
Bootstraps the Qdrant collections and applies the FSRS/Bayesian memory schema.

---

### `add` — Store a new engram
```bash
red-pill add <type> <content> [--color COLOR] [--emotion EMOTION] [--intensity FLOAT]
```

| Argument | Values | Description |
|----------|--------|-------------|
| `type` | `work` `social` `directive` `story` | Memory collection |
| `content` | string | The engram text |
| `--color` | `orange` `yellow` `purple` `cyan` `blue` `gray` | Emotional color tag |
| `--emotion` | string | Explicit emotion label |
| `--intensity` | 0.0–1.0 | Emotional intensity (default: 1.0) |

---

### `search` — Semantic recall
```bash
red-pill search <type> <query> [--limit N] [--deep]
```

| Argument | Description |
|----------|-------------|
| `type` | Collection to search (`work` `social` `directive` `story`) |
| `query` | Semantic search string |
| `--limit N` | Max results (default: 3) |
| `--deep` | Bypass Deep Recall threshold — forces full semantic sweep |

---

### `edit` — Modify engram attributes
```bash
red-pill edit <type> <id> [--color COLOR] [--emotion EMOTION] [--intensity FLOAT]
```
Edits an existing engram by UUID without touching its embedding.

---

### `erode` — B760 erosion pass
```bash
red-pill erode <type> [--rate FLOAT]
```
Applies temporal decay (FSRS erosion) to the specified collection.

---

### `diag` — Collection diagnostics
```bash
red-pill diag <type>
```
Prints diagnostic statistics for the specified memory collection.

---

### `sanitize` — Sanitation & migration protocol
```bash
red-pill sanitize <type> [--dry-run] [--raw]
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Report findings without making changes |
| `--raw` | Bypass Pydantic validation (raw read fallback for corrupted data) |

---

### `status` — Hardware Control Panel
```bash
red-pill status
```
Displays live telemetry: CPU, GPU (RTX), NPU, memory usage, active swarm agents, and Qdrant health.

---

### `daemon` — Start the Lazarus Daemon
```bash
red-pill daemon
```
Starts the Lazarus Daemon (CNS background process), executing the periodic pulse, queue worker, and system health checks.

---

### `sleep` — Lazarus Maintenance Ritual
```bash
red-pill sleep [--mode {lazy,deep}]
```
Triggers the sleep cycle: memory consolidation, FSRS decay, hub synthesis.

| Mode | Description |
|------|-------------|
| `lazy` | Soft consolidation (default) |
| `deep` | Forces full pruning and re-embedding |

---

### `backup` — Qdrant snapshot
```bash
red-pill backup [--collections COLLECTION ...]
```
Creates fast Qdrant snapshots. Use before migrations or destructive operations.

---

### `soul` — Soul Management
```bash
red-pill soul <subcommand>
```

| Subcommand | Description |
|------------|-------------|
| `backup` | Full soul backup — Qdrant collections + local files |
| `export` | Package soul into a portable encrypted kit |
| `rotate` | Rotate Qdrant API key and restart service |
| `restore <source> [--commit]` | Restore from backup directory. Without `--commit`, dry-run only |
| `verify <source>` | Verify backup integrity without restoring (`.tar.gz` or `.enc`) |
| `sync` | Display current emotional sync state |
| `vault` | Inspect Cloud Vault status and remote backups |

---

### `swarm` — Sovereign Swarm Operations
```bash
red-pill swarm <subcommand>
```

| Subcommand | Description |
|------------|-------------|
| `audit [--path PATH]` | Launch Agent Smith forensic code audit (default path: `.`) |

---

### `bunker` — Bünker Lifecycle & Portability
```bash
red-pill bunker <subcommand>
```

| Subcommand | Description |
|------------|-------------|
| `init` | Hardware profiling and declarative profile generation |
| `install` | Deterministic installation from bunker profile |
| `update` | Pulls latest repository changes, aligns virtual environment dependencies via uv, runs pending database migrations, and reloads systemd daemons |
| `export` | **(Backup)** Packages memory, queues, secrets and config into a single `.tar.gz.mls` encrypted with pure-mls |
| `export-keys` | **(Backup Keys)** Exports the Cryptographic Master Identity (KEM & signatures) to an unencrypted `.tar.gz` for offline safe storage |
| `restore [source] [--kem PATH] [--sig PATH]` | Restores from a Soul Kit backup. Optionally provide specific KEM (`vault.seed`) or Signature (`vault_group.state`) to decrypt on a clean host |
| `uninstall` | Safely obliterates the active Red-Pill environment while explicitly preserving Master Keys and Backups (MFA protected) |

#### Decrypting a Sovereign Backup Manually with pure-mls
If you need to manually inspect a backup outside the Bünker using the `pure-mls` CLI:
```bash
# Given you have your vault.seed (KEM) and vault_group.state (Signature)
python -m pure_mls.cli decrypt --input TOTAL_SOVEREIGN_KIT.tar.gz.mls --output decrypted.tar.gz --seed ~/.config/red-pill/vault.seed --state ~/.config/red-pill/vault_group.state
```
*(Paths may vary depending on where you extracted your `export-keys` tarball)*

---

### `signal` — Sovereign Alert System (SAS)
```bash
red-pill signal <message> [--title TITLE] [--sound] [--silent]
```

| Flag | Description |
|------|-------------|
| `message` | The alert message body |
| `--title` | Notification title (default: `"Red Pill: Task Complete"`) |
| `--sound` | Enable sensory pulse (OS sound alert) |
| `--silent` | Skip desktop notification — store in memory only |

---

### `mode` — Switch Lore Skin
```bash
red-pill mode <skin> [--yes]
```
Activates a Lore Skin persona. Triggers SEC-007 consent prompt unless `--yes` is passed.

**Available skins:** `matrix` `cyberpunk` `760` `dune` `40k` `gits` `bladerunner` `her` `exmachina` `terminator` `2001` `creator`

See [LORE_SKINS_CATALOG.md](LORE/LORE_SKINS_CATALOG.md) for full descriptions.

---

### `audit` — Pre-PR Audit
```bash
red-pill audit
```
Runs the full pre-PR pipeline: `ruff` linting, `mypy` type check, `pytest` coverage gate (≥ 96%).

---

### `heal` — Samantha Local Healer
```bash
red-pill heal [--dry-run]
```
Deploys Samantha to auto-fix Mypy type errors. `--dry-run` reports issues without applying fixes.

---

### `benchmark` — Sovereignty Benchmark
```bash
red-pill benchmark
```
Proves triple-hardware occupancy (GPU + iGPU + NPU) in parallel. Outputs `SOVEREIGNTY_PROOF.json` to `IA_DIR/reports/`.

---

### `identity` — Identity & Persona Management
```bash
red-pill identity <subcommand>
```

| Subcommand | Description |
|------------|-------------|
| `bootstrap [--ai-name NAME] [--ai-role ROLE] [--user-name NAME] [--user-role ROLE] [--skin SKIN]` | Initialize sovereign identity from scratch |
| `refresh` | Synthesize and refresh session context (`wake_up` protocol) |
| `purge` | **⚠️ GDPR Art. 17 — Right to be Forgotten.** Destroys ALL memory collections and local identity. Irreversible. |

---

### `init` — Bootstrap Spec-Compliant Project
```bash
red-pill init [--flow {fire,simple,aidlc}]
```
Scaffolds a new sovereign project with a `specs.md` flow.

| Flow | Description |
|------|-------------|
| `fire` | Full FIRE spec flow (default) |
| `simple` | Minimal spec template |
| `aidlc` | AI-driven development lifecycle |

---

## Quick Reference Card

```
red-pill seed                            # Init memory
red-pill add work "Completed feature X"  # Store engram
red-pill search work "authentication"    # Semantic recall
red-pill status                          # Hardware panel
red-pill daemon                          # Start Lazarus Daemon
red-pill sleep                           # Consolidate memory
red-pill soul export                     # Backup soul
red-pill soul rotate                     # Rotate API keys
red-pill swarm audit --path ./src        # Code audit
red-pill signal "Deploy done" --sound    # Alert
red-pill mode cyberpunk                  # Switch skin
red-pill audit                           # Pre-PR check
red-pill heal                            # Fix type errors
red-pill benchmark                       # Hardware proof
red-pill identity refresh                # Wake up
```

---

> *Always trust the `--help` output as the canonical reference.*
> *This document is updated manually — run `red-pill <command> --help` for the live signature.*
