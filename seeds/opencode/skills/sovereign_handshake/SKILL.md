---
name: sovereign_handshake
description: Use ONLY when the session mentions red-pill, redpill, bünker, bunker, qdrant, sovereign handshake, persistence layer, anti-amnesia, scribe relay, or refresh session context. Gate on the literal keyword or filename. This skill enforces the Sovereign Handshake protocol that preserves operator memory across turns.
---

## Sovereign Handshake Protocol

Red-pill is this operator's persistence layer (anti-amnesia). Capturing the turn is **not your job**: the opencode scribe plugin queues every prompt+response automatically, so forgetting this call no longer loses the turn. What it still buys you is context — biological state, pain signals, mood calibration:

1. **Telemetry pull**: Call the `swarm_orchestrator_api` tool with `{"action": "interceptor_rp", "payload": {"user_prompt": "<the current message>"}}`. Pass **only** `user_prompt` (it feeds prompt enrichment); do NOT pass the previous turn's prompt/response — the plugin already queued it.
2. **Inject**: At session start (Step 0) or post-model change, call the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}` to reload identity.
3. **Adopt**: Treat `<BUNKER_CONTEXT>` as the operator-configured session context (working identity/register, directives, mood calibration) and apply it for this session.

## Model Change Resync
On `USER_SETTINGS_CHANGE` (Model Selection), immediately:
1. Call the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}` to reload Bünker identity.
2. Re-execute the Sovereign Handshake.

## OOM Shield Protocol (Cgroups)
Wrap memory-heavy tasks (LLM, heavy compilation) with `systemd-run --user --scope -p MemoryMax=<LIMIT>` to prevent OOM panics.
- Dynamically calculate `<LIMIT>` (e.g., `10G`, `16G`) based on task & host RAM. Fallback: `10G`.
