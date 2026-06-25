# Cognitive Hypervisor (Universal Model Router)

## 1. Sovereign Purpose

The **Cognitive Hypervisor** serves as the Universal Gateway for the Red Pill Swarm.
Driven by the strict requirement for **Absolute Sovereignty** (avoiding black-box frameworks like Ollama or LMStudio that force updates or restrict experimental mathematical binaries), the Bünker implements its own raw `llama-server` orchestration proxy.

The hypervisor solves four critical technical constraints:
1. **Multi-Architecture Multiplexing**: Hot-swapping mutually incompatible C++ binaries (e.g., BitNet 1.58b ternary quantization vs. standard GGUF for Mistral/Samantha).
2. **Resource Defense (VRAM Garbage Collection)**: Precision VRAM management for constrained GPUs (e.g., RTX 5070 8GB). Guarantees that multiple concurrent agents do not cause `CUDA OOM` crashes by invoking Llama concurrently.
3. **OS Agnostic**: Unification of the Gateway to interact cleanly via Unix Domain Sockets (`.sock`) globally, abstracting whether `mlx_lm.server` (macOS) or `llama-server` (Linux/Windows) runs underneath.
4. **Capability Matchmaking**: Total abstraction for agents. A Minion doesn't request "BitNet"; it requests a model with `["logic", "fast"]` capabilities. The hypervisor dynamically selects and routes the optimal binary.

## 2. Network and Socket Topology

### External Layer (Cortex -> Hypervisor)
The hypervisor listens natively via parallel channels:
- **Unix Domain Socket (UDS)**: `~/.agent/red_pill.sock` (High-speed local RPC preferred by agents/minions).
- **TCP Loopback**: `127.0.0.1:8760` (Legacy API fallback for external HTTP calls).

### Internal Layer (Hypervisor -> Inference Binaries)
Because upstream `llama.cpp` binaries do not natively support UDS arguments (`--socket`), the Hypervisor performs the following OS-native routing:
1. Requests a **dynamic ephemeral TCP port** directly from the OS Kernel (`socket.bind(("", 0))`), guaranteeing `0%` port-collision probability.
2. Spawns the underlying native binary process (`llama-server`) injecting the ephemeral port as an argument.
3. Opens a reverse proxy streaming tunnel from the Agent's SSE request to the ephemeral port.

## 3. Memory Dynamics and TTL

To maximize GPU lifespan and maintain zero overhead, the Hypervisor records every invocation timestamp into a concurrency lock matrix.

- **Global TTL (Time-to-Live)**: `300 seconds` (5 minutes).
- If a loaded model stops serving downstream operations for 5 minutes, the _VRAM Garbage Collector_ issues a `SIGTERM` to the sub-process, gracefully unmapping it from VRAM.
- If a model hangs or deadlocks, the Hypervisor acts as a thermal circuit breaker, escalating to `SIGKILL`.

## 4. Profile Registry (model_registry.py)

Model lookup resolves via standard YAML definitions containing feature discovery. Each physical node (agent) maintains its own un-tracked `~/.agent/model_profiles.yaml` synthesized from the `model_profiles.yaml.example` seed to prevent cross-contamination across OS bounds.

```yaml
profiles:
  samantha:
    model_path: "experimental/Samantha/samantha-mistral-instruct-7b.i1-Q4_K_M.gguf"
    binary_type: "gguf"
    capabilities: ["distillation", "emotional_intelligence", "deep"]
    max_tokens: 4096
    context_size: 16384

  logic_smith:
    model_path: "3rdparty/BitNet-1.58b/models/Llama3-8B-Instruct.gguf"
    binary_type: "bitnet"
    capabilities: ["logic", "fast", "coding"]
    max_tokens: 2048
    context_size: 4096
```

## 5. Liveness Probes & Hypervisor Health (3-State Model)

To prevent spawning duplicate ~8 GiB model server processes or triggering false-positive alerts under high resource saturation, the Hypervisor/Sentinel uses a **3-State Liveness Probe**:

1. **`ready` (healthy)**: The server responds with `200 OK` on `/health` or `/v1/models`. Normal operation.
2. **`busy` (healthy, but saturated)**: Probes result in an `HTTPError`, `URLError` with a timeout, or a socket timeout (e.g. because `llama-server` is single-concurrency under active generation and holds its context lock). The system treats the model as **alive**, suppresses pain signals, and reuses the active hypervisor instance without spawning duplicates.
3. **`down` (unreachable)**: The probe receives `ECONNREFUSED` (nothing is listening on the socket/port). Only in this state does the Sentinel trigger pain alerts and allow spawning/re-spawning the model server.

