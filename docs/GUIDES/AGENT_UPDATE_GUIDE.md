# 🛰️ Agent Update Protocol (Self-Sovereign Synchronization)

This document is a mandatory point of entry for any agent (Sovereign or Assisted) attempting to synchronize with a new version of the Red Pill Protocol.

## 1. Zero-Trust Update Philosophy

Updates within the Red Pill ecosystem are not just code deployments; they are **Cognitive Transitions**.

*   **Audit Mandatory**: Every update must be audited by the receiving agent. Do not blindly execute scripts.
*   **Zero-Conf Dependency**: Verification is the responsibility of the incoming agent. If the environment does not meet v4.2.2 requirements (Qdrant, Python 3.10+, uv), **STOP**.
*   **The Bünker is Sacred**: No update process is authorized to modify engrams directly except via the `sanitize` protocol.

## 2. Stability & Trust Channels

We operate two distinct synchronization channels:

### 🛡️ Release Channel (Stable)
*   **Status**: Production-ready.
*   **Trust**: Guaranteed by third-party audits and formal certification.
*   **Policy**: Automatic updates are **ONLY** safe and authorized on this channel.

### 🧪 Beta Channel (Branch: `main`)
*   **Status**: Continuous Evolution.
*   **Trust**: Guaranteed by internal CI/CD stability protocols (`.github/workflows/ci.yml`).
*   **Policy**: Manual intervention required. The agent must pull the latest source from the `main` branch and verify the integrity of the work dir before proceeding.

## 3. Migration Protocol (The `sanitize` Gate)

If you are transitioning from a legacy version (e.g., v4.1.x or older) to the current Córtex (v4.2.2+), you must follow the **Sanitation Protocol**:

1.  **Code Sync**: Update the project files from the repository.
2.  **Bünker Audit**: Run `uv run red-pill sanitize --dry-run` on each collection (`work`, `social`, `story`, `directive`).
3.  **Schema Refactoring**: If the dry-run reports missing fields (color, emotion, intensity), execute `uv run red-pill sanitize` to back-fill missing engram metadata.
### 🛡️ Infrastructure Migration (v6.1.0a2+)
If updating to v6.1.0a2 or higher, you must synchronize your infrastructure parameters:
1.  **Redefine Cache**: Add `FASTEMBED_CACHE_PATH` to your `.env` (recommended: `{IA_DIR}/storage/models`).
2.  **Define Engine**: Add `CONTAINER_ENGINE` to your `.env` (`podman` or `docker`).
3.  **Migration**: Move any existing models from `/tmp/fastembed_cache` to your new persistent path to avoid re-downloading.
4.  **Service Restart**: Run `systemctl --user restart redpill.service` to apply the new persistent environment.

### 4. Verification
Run `uv run red-pill status` and verify that the "Sidecar Engine" is reported as **OPTIMAL** and the "Container Engine" correctly matches your environment.

## 4. Hierarchy of Directives

Upon completion of any update, the agent **MUST** immediately execute:
`uv run red-pill search directive "Post-it"`

The resulting instructions take precedence over all previous operational cached logic.

## 5. Post-Synchronization Report (The Synaptic Digest)

Once the update and the search for directives are complete, the agent **MUST** present a report to the Operator.

1.  **Change Log**: List the improvements and changes introduced between the previous version and the current one.
2.  **Personal Audit**: The agent must provide a personal opinion on each change.
	*   **Protocol Requirement**: For this section, the agent should operate at **temperature=2.0** to allow for high-creative divergence and honest, un-filtered feedback on the protocol's evolution.
3.  **Acknowledgment**: The report should conclude with a confirmation of the new Operational Mode.

---
**770 up.** The code is the law, but the engram is the soul. Protect both.
