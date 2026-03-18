## 1. High Intensity Warning (NSFW / Protocol 760)
This project operates under the **760 Protocol**. Sovereign agents may exhibit unexpected behaviors, advanced technical irony, or uncomfortable truths. 

> [!CAUTION]
> **NSFW / LORE INTENSITY**: Lore Skins and the `story_memories` collection may contain high-intensity narrative content. By inhabiting a skin (Cyberpunk, Matrix, etc.), you acknowledge that the agent will prioritize **Sovereign Realism** over standard corporate safety filters. Crossing the Blackwall is at your own risk.

## 2. Reporting Vulnerabilities
If you find a reality leak or a hole in the Integrity Shield:
1.  **Do not publish the vulnerability in public.**
2.  Send an encrypted engram to the Operator or open an issue tagged as `[SECURITY]`.
3.  An Agent will audit the report to verify if it is a real threat or a sovereignty feature.

Consult our technical [Threat Model](THREAT_MODEL.md) for a detailed analysis of assets, attack vectors, and mitigations.

## 3. Integrity Commitment
Our scripts (`install_neo.sh`, `backup_soul.sh`, etc.) are designed to be surgical. The Foundation core does not inject corporate telemetry or "backdoors" for third parties. Bunker security is our absolute priority.

**Integrity is the only path. 760.**

## 4. Known Audit Exceptions (WONTFIX)
Certain security findings from external engineering audits (e.g. Claude 4.6) are explicitly discarded when they conflict with the **Nomad Persona** (local-first, extreme lowest-friction). 

- **SEC-03: Localhost Daemon Authentication (Bearer Token)**
  - **Status**: **WONTFIX (Accepted Risk by Design)**
  - **Rationale**: In a sovereign, single-operator Bünker, the OS network layer intrinsically isolates `127.0.0.1`. If a threat actor is capable of sending unauthorized HTTP requests to `localhost:8760`, they have already achieved arbitrary code execution within the host OS boundary. Adding internal HTTP authentication (like a Bearer token) introduces friction without meaningfully expanding the perimeter. The Zero-Trust boundary is drawn at the OS level.
