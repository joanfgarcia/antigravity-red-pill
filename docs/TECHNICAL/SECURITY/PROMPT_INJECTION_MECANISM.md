# The Bünker: Prompt Injection Mechanisms

The architecture of *The Bünker* (Red Pill Protocol) manages User and System context through two distinct prompt injection philosophies. These are designed to maintain Zero-Trust principles and guarantee Zero-Latency operations within the Operator's IDE.

---

## 1. Passive Injection (Zero-Latency / Native IDE Rules)
> **Recommended for continuous telemetry (LED Panels, system alerts, hardware status).**

Instead of intercepting the text the Operator types into the IDE on the fly, the background process `bunker_telemetry.py` proactively writes vital information into **strategic Markdown files** that modern IDEs automatically load as *System Prompts* or *Rules*.

### Natively Supported by `bunker_telemetry.py`:
- **Antigravity (Gemini)**: Periodically writes to `~/.gemini/antigravity/rules/00_bunker_telemetry.md`. Antigravity includes it globally with no extra configuration.
- **Cursor IDE**: Writes to `<PROJECT_ROOT>/.cursor/rules/00_bunker_telemetry.mdc`. Cursor includes this contextually within the local project.
- **Generic Fallback**: Writes to `<PROJECT_ROOT>/.bunker_telemetry.md`. In IDEs like Windsurf or GitHub Copilot, the Operator must manually reference this file (e.g., typing `@.bunker_telemetry.md` or including it in `.github/copilot-instructions.md`).

**Advantages:**
Asynchronous CPU loads. The daemon formats the information (Qdrant queues, GPU usage, Minion inbox) without blocking the user's prompt during inference. It is mathematically impossible for it to break the local network loop or generate API *timeouts*.

**Limitations:**
It cannot understand the *semantic intent* of the user's prompt to search for specific context (That is what Active Injection is for).

---

## 2. Active Injection (MCP Interceptor / RAG)
> **Recommended for semantic retrieval (Deep RAG) or strict security routing.**

Through the MCP (Model Context Protocol) server, we deploy `mcp_server.py`. Historically, we unified the `interceptor_rp` tool to pause the prompt, query the Vector databases (Qdrant) to retrieve memories, and finally inject the semantic result into the LLM header.

**Current State:**
The fully active pipeline was de-prioritized due to *timeouts* introduced by local SLMs and Qdrant cold starts. Instead, the system now relies on the **Silent Scribe** (`mcp_RedPill-Kernel_memorize_interaction`), which agents initiate voluntarily at the end of a cycle to avoid breaking the human feedback loop.

### How to Enable Active Injection:
If a future Operator desires active injection on every prompt, they must connect their IDE's MCP client to a Local Proxy that orchestrates the call before reaching the Cloud API (e.g., routing through a local FastAPI proxy).
