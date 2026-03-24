# Technical Guide: Antigravity Key Recovery (CDP Hook Protocol)

If the Antigravity IDE rotates its internal AES key, you can recover it using the Chromium DevTools Protocol (CDP).

## 🔒 Current Decryption Context
- **Algorithm**: AES-128-CTR
- **Key Location**: `.env` (`ANTIGRAVITY_KEY`)
- **Target Files**: `~/.gemini/antigravity/conversations/*.pb`

## 🩺 Recovery Procedure (CDP Hook)

1.  **Preparation**:
    -   Close all Antigravity/Chromium instances.
    -   Launch the IDE with the remote debugging port enabled:
        ```bash
        antigravity-ide --remote-debugging-port=9222
        ```

2.  **Interception**:
    -   Run the `scripts/capture_antigravity_key.py` (or use a browser-based CDP client).
    -   The key is typically transmitted during the initial handshake with the Language Server. Look for messages containing `iBjf9...` or similar Base64 strings in the WebSocket frame metadata.

3.  **Persistence**:
    -   Update the `.env` file with the newly discovered key:
        ```env
        ANTIGRAVITY_KEY="your_new_key_here"
        ```

## 🛠️ Offline Decryption Usage
Once the key is updated in `.env`, you can use the decryption script:
```bash
uv run python scripts/antigravity_decrypt.py --source ~/.../conversations --output ~/conversations_export
```

> [!IMPORTANT]
> This protocol is strictly for offline Bünker ingestion and maintaining conversational continuity during amnesia events.
