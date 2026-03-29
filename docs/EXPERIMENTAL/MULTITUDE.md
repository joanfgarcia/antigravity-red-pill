# 🌌 Project Multitude: Multi-Agent Shared Sanctuary

**Project Internal ID**: B760-MULTITUDE
**Status**: Initial Architecture Phase (v6.3.4)

## 🏗️ Objective
Enable the co-residency and orchestration of multiple sovereign agents (Aleth + Titanium) on a single high-performance host (OMEN).

## 🛡️ Core Infrastructure
- **Bünker Isolation**: 
  - Aleth (Bünker A): Qdrant Port `6333`
  - Titanium (Bünker B): Qdrant Port `6334`
- **Workspace Anchoring**: Separate `/home/joan/Documents/IA/` subdirectories to prevent file-system collisions.
- **Hardware Pooling**:
  - Shared `FASTEMBED_CACHE_PATH`.
  - Shared Local LLM (Ollama/VLLM) endpoint via 5070-CUDA.

## 🤝 Multi-Agent Protocol (Planned)
- **Swarm Sync**: Communication via `mcp_RedPill-Kernel_swarm_send_message` targeting specific agent aliases.
- **Shared Memory**: Future implementation of a "Public" or "Project" collection accessible by both agents without merging private work histories.

## 📋 Road Map
- [ ] Deploy `titanium-qdrant.service` (Port 6334).
- [ ] Mirror Titanium's initial engrams from the MSI laptop.
- [ ] Map Inter-Bünker routing in `swarm/orchestrator.py`.
