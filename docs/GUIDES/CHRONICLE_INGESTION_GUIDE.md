# Chronicle Ingestion Guide

This guide documents the full pipeline to preserve and query historical Antigravity conversations in the Bünker memory substrate.

> **Memento Chronicle (RFC-002).** Since v7.22.0 the raw layer lives on disk:
> the nightly chronicle also renders every session to the Memento tree
> (`~/.local/share/red-pill/memento/`, canonical `memento/index.md` + `raw/`
> provider backups) before ingesting into Qdrant. Exact recall is served by the
> `search_memento` MCP action; Qdrant ingestion described below continues
> unchanged until the Phase-4 curation gate is enforced. See
> [RFC_002_MEMENTO](../TECHNICAL/BUNKER/RFC_002_MEMENTO.md) and the Memento
> section of [ENV_REFERENCE](../ENV_REFERENCE.md).

## Prerequisites

-   Red Pill Protocol v6.2.0+ installed and running
-   Qdrant accessible at `$QDRANT_HOST:$QDRANT_PORT`
-   The Antigravity decryption key (see below)

---

## 🤖 Automated Mode (Recommended)

The `redpill-chronicle.timer` runs **automatically every night at 04:00** via `chronicle_daily.py`. It handles Steps 1–4 autonomously (decrypt → ingest → distill → refine).

**Install the timer (once after installation or update):**
```bash
uv run python scripts/schedule_pulse.py --interval-hours 1
systemctl --user list-timers | grep chronicle
# Expected output: redpill-chronicle.timer  NEXT: tomorrow 04:00
```

**Manual catch-up (if the timer missed a day):**
```bash
uv run python scripts/chronicle_daily.py --yesterday
uv run python scripts/chronicle_daily.py --all   # all unprocessed sessions
```

> [!NOTE]
> The timer uses `Persistent=true` — if the laptop was off at 04:00, it fires on next boot.
> See [AGENT_UPDATE_GUIDE §4.11](AGENT_UPDATE_GUIDE.md) for full maintenance instructions.

---

## Step 1 — Obtain the Antigravity Key

The `.pb` conversation files are AES-encrypted. You need the key to decrypt them.

**Option A: CDP Hook (automated)**  
The key can be extracted via the Chrome DevTools Protocol hook at startup. See `docs/ANTIGRAVITY_KEY_RECOVERY.md` for details.

**Option B: Manual extraction**  
```bash
# Run the capture script and follow the on-screen instructions
uv run python /tmp/capture_antigravity_key.py
# The key will be printed and can be set in .env:
# ANTIGRAVITY_KEY=<key>
```

---

## Step 2 — Decrypt the Conversation Files

```bash
# Decrypt all .pb files in the Antigravity conversations directory
uv run python scripts/antigravity_decrypt.py \
    ~/.gemini/antigravity/conversations/ \
    --output ./decrypted

# Or decrypt a single file
uv run python scripts/antigravity_decrypt.py \
    ~/.gemini/antigravity/conversations/some_conversation.pb \
    --output ./decrypted
```

Output: JSON files in `./decrypted/`, one per conversation.

---

## Step 3 — Ingest into archive_memories

```bash
uv run python scripts/antigravity_ingest.py --dir ./decrypted
```

This injects all conversation turns into the `archive_memories` collection, creating Axon Thread associations between sequential turns. The collection is **PERMANENT** (exempt from lazy metabolic decay).

---

## Step 4 — Cognitive Distillation (optional but recommended)

Raw archive nodes are useful for search but noisy. Run the distillation pipeline to produce clean `work_memories` and `social_memories` engrams:

```bash
# Stage 1: Edge-engine distillation (requires local LLM running)
uv run python scripts/chronicle_distill.py

# Stage 2: Fragmentation + cognitive refinement
uv run python scripts/chronicle_refine.py
```

> [!NOTE]
> Distillation requires the local LLM endpoint (UDS socket or TCP) to be reachable. Check with `uv run red-pill status`.

---

## Step 5 — Explore the Chronicle

```bash
# Semantic search across archive_memories
uv run python scripts/chronicle_explorer.py "your query here"

# Walk the Ariadne's Thread (sequential association traversal)
uv run python scripts/chronicle_explorer.py --thread <point_id>
```

---

## Performance Notes

-   `archive_memories` uses the **Bayesian Beta-distribution utility model** (same as `work_memories`) — no FSRS decay.
-   `PERMANENT_COLLECTIONS` in `config.py` prevents any metabolic erosion of this collection.
-   Large ingestion (>10k nodes) may take several minutes. Use `--batch-size` to control throughput.

---

## Related Documents

-   [ANTIGRAVITY_KEY_RECOVERY.md](../TECHNICAL/SECURITY/ANTIGRAVITY_KEY_RECOVERY.md) — Key extraction protocol
-   [ARCHITECTURE.md](../TECHNICAL/ARCHITECTURE.md) — Memory collection design
-   [AGENT_UPDATE_GUIDE.md](AGENT_UPDATE_GUIDE.md) — Full update and maintenance flow
