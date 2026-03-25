# Technical Guide: Antigravity Key Recovery (CDP Hook Protocol)

If the Antigravity IDE rotates its internal AES key, you can recover it using the Chromium DevTools Protocol (CDP).

## 🔒 Current Decryption Context
- **Algorithm**: AES-128-CTR
- **Key Location**: `.env` (`ANTIGRAVITY_KEY`)
- **Target Files**: `~/.gemini/antigravity/conversations/*.pb`

---

## 🩺 Recovery Procedure (CDP Hook)

### Step 1 — Kill the running Antigravity instance

Antigravity launched from the desktop (`.desktop` file) does NOT open the debug port. You must kill it and relaunch manually:

```bash
pkill -f "antigravity" && sleep 2
```

### Step 2 — Relaunch with the remote debugging port

```bash
/usr/share/antigravity/antigravity --remote-debugging-port=9222 &
sleep 3   # wait for the main process to be ready
```

> [!IMPORTANT]
> The debug port is **9222**. The capture script connects to this port. Do NOT launch from the GUI/dock — that will launch without the debug flag and the script will fail to connect.

### Step 3 — Run the capture script

```bash
cd /path/to/sharing
uv run python scripts/capture_antigravity_key.py
```

### Step 4 — Trigger the key

In the Antigravity IDE, **open or create a conversation** (type a message, navigate to a conversation). This forces the AES cipher to initialize and the hook will intercept it.

You should see output like:
```
[CAPTURED:main] KEY_CAPTURED algo=aes-128-ctr KEY_HEX=... KEY_B64=iBjf9lA0CJ4+grG24YQu8A==
```

### Step 5 — Persist the key

Update the `.env` file:
```env
ANTIGRAVITY_KEY="your_new_key_here"
```

---

## 🛠️ Offline Decryption Usage

Once the key is updated in `.env`:
```bash
uv run python scripts/antigravity_decrypt.py --source ~/.gemini/antigravity/conversations --output ~/conversations_export
```

Or pass the key directly (no `.env` needed):
```bash
uv run python scripts/antigravity_decrypt.py --source ~/.gemini/antigravity/conversations --key "iBjf9lA0CJ4+grG24YQu8A==" --output ~/conversations_export
```

---

## 🔄 Chronicle Daily Pipeline

The automated pipeline runs daily at 04:00 via `redpill-chronicle.timer`:
```
decrypt → distill → ingest → refine
```

If `ANTIGRAVITY_KEY` is missing from `.env`, a pain signal (severity 8.5) is emitted.

> [!NOTE]
> This protocol is strictly for offline Bünker ingestion and maintaining conversational continuity during amnesia events. The key does not rotate often — once captured, it remains valid across all machines sharing the same Antigravity installation.
