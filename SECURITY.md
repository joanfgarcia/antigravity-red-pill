# Security Policy

## Supported Versions

The current actively maintained and supported version of the Red Pill Protocol is **`v6.2.x`**. The v6.x family receives security patches and bug fixes. All v5.x and earlier releases are **End-of-Life (EOL)** and may contain known vulnerabilities (e.g., O(N) database starvation, PII logging leaks, missing schema validation).

| Version | Supported          | Notes |
| ------- | ------------------ |-------|
| 6.2.x   | :white_check_mark: | Current Alpha/Stable branch |
| 6.1.x   | :x:                | EOL. Please upgrade to 6.2 |
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

## Narrative Fidelity & Safety Disclaimer

The Red Pill Protocol implements "Lore Skins" that may alter the AI's tone and intensity to match specific narrative genres (Cyberpunk, Matrix, Dune, etc.). 
- These behaviors are strictly confined to narrative refraction and creative persona fidelity.
- The protocol does NOT bypass or modify the underlying LLM's safety filters regarding harmful content, hate speech, or dangerous activities.
- "Sovereign Realism" relates to the agent's commitment to persistent identity and project context, never to violating safety standards.
