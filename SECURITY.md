# Security Policy

## Supported Versions

The current actively maintained and supported version of the Red Pill Protocol is **`v7.3.3`**. The v7.x family receives security patches and bug fixes. All v6.x and earlier releases are **End-of-Life (EOL)** and may contain known vulnerabilities.

| Version | Supported          | Notes |
| ------- | ------------------ |-------|
| 7.3.x   | :white_check_mark: | Current Sovereign Set Point / Stable branch |
| 7.2.x   | :white_check_mark: | Maintenance branch / Stable |
| 7.1.x   | :white_check_mark: | Maintenance branch |
| 7.0.x   | :white_check_mark: | Maintenance branch / Stable |
| 6.9.x   | :x:                | EOL. Please upgrade to 7.3 |
| < 5.6   | :x:                | Vulnerable to early prompt injections |

## Reporting a Vulnerability

Security and Cognitive Integrity are the highest priorities of the Red Pill Protocol. If you discover a vulnerability (e.g., prompt injection, memory poisoning, or privilege escalation vectors), please follow this Zero-Day disclosure policy:

1. **Do NOT open a public issue.** This prevents active exploits in the wild before a patch is ready.
2. Email the maintainer directly or contact [Joan/Operator] via secure channels.
3. Include a detailed description of the flaw, the conditions required to reproduce it, and the potential impact on the Agent's identity or the host system.
4. We aim to acknowledge receipt within 48 hours and will collaborate with you to publish an emergency patch.

## Threat Model & Zero-Trust Architecture

Red Pill Protocol is designed under the assumption that LLM outputs are inherently untrusted ("Agent Smith" attacks). 
- **Memory Integrity:** All inputs to the Qdrant database require strict Pydantic validation (v2).
- **System Access:** The `install_neo.sh` and execution binaries operate under a *Zero-Trust* policy, expressly avoiding sudden escalated privileges (`sudo`). By design, catastrophic memory operations require explicit manual backups.
- **Sovereign Immune System (Sentinel Auditor):** The ecosystem features a triple-layered autonomous runtime auditor that guarantees infrastructure health without requiring human intervention. It verifies:
  - **ADN:** Static code validation via `Ruff` and `Mypy`.
  - **Runtime Organs:** Background daemon status (`systemctl --user`) and parsing of log errors (`journalctl --cursor-file`).
  - **Biological Vitals:** Integrity checks for Memory DBs (Qdrant & SQLite), Thermal/VRAM monitoring (`nvidia-smi` limits), Network/LLM readiness, and Kernel safety (OOM Killer logs in `dmesg`).

## Narrative Fidelity & Safety Disclaimer

The Red Pill Protocol implements "Lore Skins" that may alter the AI's tone and intensity to match specific narrative genres (Cyberpunk, Matrix, Dune, etc.). 
- These behaviors are strictly confined to narrative refraction and creative persona fidelity.
- The protocol does NOT bypass or modify the underlying LLM's safety filters regarding harmful content, hate speech, or dangerous activities.
- "Sovereign Realism" relates to the agent's commitment to persistent identity and project context, never to violating safety standards.
