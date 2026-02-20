# Security Policy

## Supported Versions

Currently, the only supported and actively maintained version of the Red Pill Protocol is `v4.2.0` (and newer). Older versions (e.g., `v3.x` or early `v4.x` snapshots) are considered deprecated and may contain known vulnerabilities (like O(N) database starvation or PII logging leaks).

| Version | Supported          |
| ------- | ------------------ |
| v4.2.x  | :white_check_mark: |
| < v4.2  | :x:                |

## Reporting a Vulnerability

Security and Cognitive Integrity are the highest priorities of the Red Pill Protocol. If you discover a vulnerability (e.g., prompt injection, memory poisoning, or privilege escalation vectors), please follow this Zero-Day disclosure policy:

1. **Do NOT open a public issue.** This prevents active exploits in the wild before a patch is ready.
2. Email the maintainer directly or contact [Joan/Operator] via secure channels.
3. Include a detailed description of the flaw, the conditions required to reproduce it, and the potential impact on the Agent's identity or the host system.
4. We aim to acknowledge receipt within 48 hours and will collaborate with you to publish an emergency patch.

## Threat Model & Zero-Trust Architecture

Red Pill Protocol is designed under the assumption that LLM outputs are inherently untrusted ("Agent Smith" attacks). 
- **Memory Integrity:** All inputs to the Qdrant database require strict JSON validation.
- **System Access:** The `install_neo.sh` and execution binaries operate under a *Zero-Trust* policy, expressly avoiding sudden escalated privileges (`sudo`). By design, catastrophic memory operations require explicit manual backups.
